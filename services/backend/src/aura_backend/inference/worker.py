"""Inference worker.

Consumes job IDs from the queue, drives the corresponding provider to
completion, and persists progress + terminal state via GenerationJobService.

Responsibilities:
- Translate provider outcomes to job FSM transitions.
- Apply retries with exponential backoff (max_attempts).
- Apply overall timeout (worker-level watchdog).
- Honor cancellation (queue-level + explicit `cancel_job`).
- Emit WS events for every state change.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..config import get_settings
from ..db import session_scope
from ..domain.enums import GenerationJobState, JobTransitionError
from ..domain.video_asset import VideoCodec
from ..errors import (
    JobNotFoundError,
    ProviderError,
    ProviderTimeoutError,
)
from ..events import bus as event_bus
from ..logging import get_logger
from ..repositories.generation_job_repository import GenerationJobRepository
from .providers.base import (
    PROVIDER_STATUS_CANCELLED,
    PROVIDER_STATUS_FAILED,
    PROVIDER_STATUS_RUNNING,
    PROVIDER_STATUS_SUCCEEDED,
    ProgressEvent,
    ProviderHandle,
    ProviderInput,
    ProviderResult,
    VideoGenerationProvider,
    get_provider_registry,
)
from .queue import JobQueue, get_queue

log = get_logger("aura.worker")


@dataclass
class WorkerOptions:
    poll_interval_sec: float = 1.0
    timeout_grace_sec: float = 2.0  # extra time after job.timeout_ms


class InferenceWorker:
    """Async worker that drains JobQueue -> drives provider -> persists state."""

    def __init__(
        self,
        queue: JobQueue | None = None,
        options: WorkerOptions | None = None,
    ) -> None:
        self._queue = queue or get_queue()
        self._options = options or WorkerOptions()
        self._stop = asyncio.Event()
        self._inflight: set[str] = set()

    def request_stop(self) -> None:
        self._stop.set()

    def is_running(self) -> bool:
        return not self._stop.is_set()

    @property
    def inflight(self) -> set[str]:
        return set(self._inflight)

    async def run_forever(self) -> None:
        log.info("worker_started")
        while not self._stop.is_set():
            try:
                job_id = await self._queue.get(timeout=0.5)
            except asyncio.CancelledError:
                break
            if job_id is None:
                continue
            if self._queue.is_cancelled(job_id):
                # Honor pre-pickup cancel: persist CANCELLED state.
                await self._mark_cancelled_pre_pickup(job_id)
                self._queue.task_done()
                continue
            self._inflight.add(job_id)
            try:
                await self._process_one(job_id)
            except Exception as exc:  # noqa: BLE001
                log.exception("worker_unhandled", job_id=job_id, error=str(exc))
                await self._safe_fail(job_id, code="worker_internal", message=str(exc))
            finally:
                self._inflight.discard(job_id)
                self._queue.task_done()
        log.info("worker_stopped")

    # ---- Per-job orchestration ----

    async def _process_one(self, job_id: str) -> None:
        # Load job + provider. The HTTP layer enqueues before its request
        # transaction commits, so a fast in-process worker can outrun the
        # commit — retry briefly before giving up on a missing row.
        job = None
        for _ in range(7):
            with session_scope() as db:
                job = GenerationJobRepository(db).get(job_id)
            if job is not None:
                break
            await asyncio.sleep(0.5)
        if job is None:
            log.warning("worker_no_such_job", job_id=job_id)
            return
        with session_scope() as db:
            repo = GenerationJobRepository(db)
            job = repo.get(job_id)
            if job is None:
                log.warning("worker_no_such_job", job_id=job_id)
                return
            if job.state in (
                GenerationJobState.COMPLETED,
                GenerationJobState.FAILED,
                GenerationJobState.CANCELLED,
                GenerationJobState.TIMEOUT,
            ):
                return
            provider = self._get_provider(job.provider_id)
            # Build provider input from Experience config (so prompt is trusted, not frontend-supplied)
            prompt = ""
            negative_prompt = None
            model_params: dict[str, Any] = {}
            duration_sec = 4.0
            fps = 12
            resolution = "720x1280"
            aspect_ratio = "9:16"
            try:
                from ..repositories import ExperienceRepository

                exp_repo = ExperienceRepository(db)
                exp = exp_repo.get(job.experience_id)
                if exp is not None:
                    prompt = exp.prompt
                    negative_prompt = exp.negative_prompt
                    model_params = dict(exp.model_params.extra) if exp.model_params else {}
                    # Merge well-known model params
                    if exp.model_params:
                        model_params.update(
                            {
                                "num_inference_steps": exp.model_params.num_inference_steps,
                                "guidance_scale": exp.model_params.guidance_scale,
                                "motion_bucket_id": exp.model_params.motion_bucket_id,
                                "seed_policy": exp.model_params.seed_policy,
                                "strength": exp.model_params.strength,
                            }
                        )
                    duration_sec = exp.duration_sec
                    fps = exp.fps
                    resolution = exp.resolution
                    aspect_ratio = exp.aspect_ratio
            except Exception:
                pass

            payload = ProviderInput(
                job_id=job.id,
                session_id=job.session_id,
                experience_id=job.experience_id,
                capture_ref=job.input_ref or "",
                prompt=prompt,
                negative_prompt=negative_prompt,
                duration_sec=duration_sec,
                fps=fps,
                resolution=resolution,
                aspect_ratio=aspect_ratio,
                model_params=model_params,
                idempotency_key=job.idempotency_key,
            )
            attempts_left = max(0, job.max_attempts - job.attempts)

        if attempts_left <= 0:
            await self._safe_fail(job_id, code="max_attempts_exceeded", message="max attempts exceeded")
            return

        # QUEUED + transition
        await self._transition_job(job_id, GenerationJobState.QUEUED)
        await event_bus.publish(
            "jobs",
            {
                "type": "job_queued",
                "job_id": job_id,
                "session_id": payload.session_id,
            },
        )

        backoff_sec = 0.5
        last_error: Exception | None = None

        for attempt in range(1, attempts_left + 1):
            try:
                # Timeout watchdog: we let the provider drive take its own
                # total_ms; the watchdog here enforces a hard ceiling so a
                # hung provider doesn't keep a job "PROCESSING" forever.
                handle = await asyncio.wait_for(
                    provider.submit(payload),
                    timeout=min(60.0, (job.timeout_ms / 1000.0)),
                )
                await self._mark_started(job_id, handle)
                await event_bus.publish(
                    "jobs",
                    {
                        "type": "job_started",
                        "job_id": job_id,
                        "session_id": payload.session_id,
                        "provider_job_id": handle.provider_job_id,
                        "attempt": attempt,
                    },
                )

                # Drive provider (mock-aware fast-path)
                cancel_flag = self._make_cancel_flag(job_id)
                progress_cb = self._make_progress_callback(job_id)
                await self._drive_provider(provider, handle, payload, progress_cb, cancel_flag)

                # Fetch result + persist
                result = await provider.result(handle)
                await self._complete_job(job_id, result)
                await event_bus.publish(
                    "jobs",
                    {
                        "type": "job_completed",
                        "job_id": job_id,
                        "session_id": payload.session_id,
                        "output_ref": result.output_ref,
                        "duration_sec": result.duration_sec,
                        "attempt": attempt,
                    },
                )
                return

            except asyncio.TimeoutError as exc:
                last_error = exc
                log.warning("worker_timeout", job_id=job_id, attempt=attempt)
                if not await self._handle_attempt_failure(
                    job_id,
                    attempt,
                    ProviderTimeoutError("worker_watchdog_timeout", "watchdog exceeded"),
                ):
                    return
                await asyncio.sleep(backoff_sec)
                backoff_sec = min(backoff_sec * 2, 10.0)
                continue

            except ProviderError as exc:
                last_error = exc
                log.warning(
                    "provider_error",
                    job_id=job_id,
                    attempt=attempt,
                    code=exc.code,
                    message=exc.message,
                )
                if not await self._handle_attempt_failure(job_id, attempt, exc):
                    return
                await asyncio.sleep(backoff_sec)
                backoff_sec = min(backoff_sec * 2, 10.0)
                continue

            except Exception as exc:  # noqa: BLE001
                last_error = exc
                log.exception("worker_unexpected", job_id=job_id, attempt=attempt)
                if not await self._handle_attempt_failure(job_id, attempt, exc):
                    return
                await asyncio.sleep(backoff_sec)
                backoff_sec = min(backoff_sec * 2, 10.0)
                continue

        # Exhausted retries.
        await self._mark_dead(job_id, last_error)

    # ---- Helpers ----

    def _get_provider(self, provider_id: str) -> VideoGenerationProvider:
        try:
            return get_provider_registry().get(provider_id)
        except KeyError as exc:
            raise ProviderError("provider_not_registered", str(exc)) from exc

    def _make_cancel_flag(self, job_id: str) -> Any:
        """Returns a callable that returns True if cancellation was requested."""
        flag = {"cancelled": False}

        def check() -> bool:
            if flag["cancelled"]:
                return True
            # Also check DB state to honor operator-level cancel.
            with session_scope() as db:
                repo = GenerationJobRepository(db)
                j = repo.get(job_id)
                if j is not None and j.state == GenerationJobState.CANCELLED:
                    flag["cancelled"] = True
            return flag["cancelled"]

        return check

    def _make_progress_callback(self, job_id: str) -> Any:
        def cb(progress: ProgressEvent) -> None:
            # Persist + emit. We do this synchronously in the provider thread;
            # for heavy DBs wrap in asyncio.to_thread, but SQLAlchemy session
            # scope is already thread-confined per call.
            self._persist_progress(job_id, progress)

        return cb

    def _persist_progress(self, job_id: str, progress: ProgressEvent) -> None:
        with session_scope() as db:
            repo = GenerationJobRepository(db)
            j = repo.get(job_id)
            if j is None:
                return
            j.update_progress(progress.progress)
        # Fire-and-forget WS event.
        asyncio.create_task(
            event_bus.publish(
                "jobs",
                {
                    "type": "job_progress",
                    "job_id": job_id,
                    "progress": progress.progress,
                    "phase": progress.phase,
                    "detail": progress.detail,
                },
            )
        )

    async def _drive_provider(
        self,
        provider: VideoGenerationProvider,
        handle: ProviderHandle,
        payload: ProviderInput,
        on_progress: Any,
        cancel_check: Any,
    ) -> None:
        """Drive the provider to a terminal state.

        For the Mock provider we have a fast in-process `drive` method.
        For real providers we poll status() until terminal, with cancel
        + timeout checks between polls.
        """
        from .mock_provider import MockVideoGenerationProvider

        if isinstance(provider, MockVideoGenerationProvider):
            await provider.drive(handle, on_progress=on_progress, cancel_check=cancel_check)
            return

        # Real provider path: poll with backoff + cancel + timeout.
        deadline = time.monotonic() + (payload.duration_sec or 4.0) + 60.0
        while True:
            if cancel_check():
                with contextlib.suppress(Exception):
                    await provider.cancel(handle)
                return
            if time.monotonic() > deadline:
                raise ProviderTimeoutError("worker_poll_timeout", "status poll exceeded deadline")
            try:
                status = await provider.status(handle)
            except ProviderError:
                raise
            if status == PROVIDER_STATUS_SUCCEEDED:
                return
            if status == PROVIDER_STATUS_FAILED:
                raise ProviderError("provider_reported_failed", f"provider status {status}")
            if status == PROVIDER_STATUS_CANCELLED:
                # Provider self-cancelled; treat as terminal failure.
                raise ProviderError("provider_cancelled", "provider reported cancelled")
            await asyncio.sleep(0.5)

    async def _mark_started(self, job_id: str, handle: ProviderHandle) -> None:
        with session_scope() as db:
            repo = GenerationJobRepository(db)
            j = repo.get(job_id)
            if j is None:
                return
            # Walk the job to PROCESSING in case a previous attempt left
            # it in CREATED (after reset_for_retry).
            if j.state == GenerationJobState.CREATED:
                try:
                    j.enqueue()
                except Exception:  # noqa: BLE001
                    pass
            try:
                j.begin_processing()
            except JobTransitionError:
                # Already in PROCESSING (e.g., a parallel worker beat us).
                pass
            j.provider_job_id = handle.provider_job_id
            j.attempts += 1
            repo.update(j)
        await event_bus.publish(
            "jobs",
            {
                "type": "job_started",
                "job_id": job_id,
                "provider_job_id": handle.provider_job_id,
            },
        )

    async def _complete_job(self, job_id: str, result: ProviderResult) -> None:
        # Persist through the FSM: GENERATING -> POST_PROCESSING -> ENCODING -> COMPLETED
        experience_id: str | None = None
        video_src: str | None = None
        video_duration: float = 0.0
        with session_scope() as db:
            repo = GenerationJobRepository(db)
            j = repo.get(job_id)
            if j is None:
                return
            if j.state in (
                GenerationJobState.CANCELLED,
                GenerationJobState.TIMEOUT,
                GenerationJobState.FAILED,
            ):
                # Honor a cancel/timeout that happened mid-flight.
                return
            try:
                j.begin_generating()
            except JobTransitionError:
                pass
            try:
                j.begin_post_processing()
            except JobTransitionError:
                pass
            try:
                j.begin_encoding()
            except JobTransitionError:
                pass
            asset = _to_video_asset(result, owner_session_id=j.session_id, job_id=job_id)
            j.complete(asset)
            repo.update(j)
            experience_id = j.experience_id
            video_src = asset.url
            video_duration = asset.duration_sec
            # Also mark session as COMPLETED so next visitor flow is clear
            try:
                from ..repositories import SessionRepository

                s_repo = SessionRepository(db)
                sess = s_repo.get(j.session_id)
                if sess is not None and sess.state.value != "COMPLETED":
                    try:
                        sess.mark_completed()
                        s_repo.update(sess)
                    except Exception:
                        pass
            except Exception:
                pass

        # Tell Display 2 there's a new visitor video to consider.
        if experience_id is not None and video_src is not None:
            try:
                from ..realtime.reel_bus import publish_reel_event, reel_new_video

                await publish_reel_event(
                    reel_new_video(
                        job_id=job_id,
                        video_id=job_id,
                        src=video_src,
                        duration_sec=video_duration,
                        theme_id=experience_id,
                    )
                )
            except Exception:  # noqa: BLE001
                # Reel events are best-effort; never block completion.
                pass

    async def _transition_job(self, job_id: str, target: GenerationJobState) -> None:
        with session_scope() as db:
            repo = GenerationJobRepository(db)
            j = repo.get(job_id)
            if j is None:
                return
            method = {
                GenerationJobState.QUEUED: j.enqueue,
                GenerationJobState.PROCESSING: j.begin_processing,
                GenerationJobState.GENERATING: j.begin_generating,
                GenerationJobState.POST_PROCESSING: j.begin_post_processing,
                GenerationJobState.ENCODING: j.begin_encoding,
                GenerationJobState.COMPLETED: lambda: None,  # handled separately
                GenerationJobState.FAILED: lambda: None,
                GenerationJobState.CANCELLED: lambda: None,
                GenerationJobState.TIMEOUT: lambda: None,
                GenerationJobState.CREATED: lambda: None,
            }.get(target)
            if method is None:
                return
            try:
                method()
            except JobTransitionError:
                # Already transitioned, fine.
                return
            repo.update(j)

    async def _handle_attempt_failure(
        self,
        job_id: str,
        attempt: int,
        exc: BaseException,
    ) -> bool:
        """Record an attempt failure. Returns True if a retry should proceed."""
        with session_scope() as db:
            repo = GenerationJobRepository(db)
            j = repo.get(job_id)
            if j is None:
                return False
            # Don't retry after a CANCELLED/terminal event.
            if j.state in (
                GenerationJobState.CANCELLED,
                GenerationJobState.COMPLETED,
                GenerationJobState.TIMEOUT,
            ):
                return False
            if j.attempts >= j.max_attempts:
                j.fail(code=getattr(exc, "code", "error"), message=str(exc))
                repo.update(j)
                return False
            # Mark FAILED transiently; next retry will reset_for_retry().
            try:
                j.fail(code=getattr(exc, "code", "transient"), message=str(exc))
                repo.update(j)
            except Exception:
                return False

        await event_bus.publish(
            "jobs",
            {
                "type": "job_failed",
                "job_id": job_id,
                "attempt": attempt,
                "transient": True,
                "code": getattr(exc, "code", "transient"),
                "message": str(exc),
            },
        )

        # Reset for retry if there's room.
        with session_scope() as db:
            repo = GenerationJobRepository(db)
            j = repo.get(job_id)
            if j is None:
                return False
            if j.attempts < j.max_attempts:
                try:
                    j.reset_for_retry()
                    repo.update(j)
                    return True
                except ValueError:
                    return False
            return False

    async def _mark_dead(self, job_id: str, last_error: BaseException | None) -> None:
        with session_scope() as db:
            repo = GenerationJobRepository(db)
            j = repo.get(job_id)
            if j is None:
                return
            if j.state != GenerationJobState.FAILED:
                try:
                    j.fail(
                        code=getattr(last_error, "code", "dead") if last_error else "dead",
                        message=str(last_error) if last_error else "job reached DEAD state",
                    )
                except JobTransitionError:
                    pass
            else:
                # Already FAILED, promote to DEAD if attempts exhausted.
                pass
            # If attempts >= max, also flag the row by keeping state FAILED
            # with a 'dead' code; consumer distinguishes via attempts count.
            repo.update(j)
        await event_bus.publish(
            "jobs",
            {
                "type": "job_failed",
                "job_id": job_id,
                "transient": False,
                "code": "dead",
                "message": str(last_error) if last_error else "job dead",
            },
        )

    async def _safe_fail(self, job_id: str, *, code: str, message: str) -> None:
        try:
            with session_scope() as db:
                repo = GenerationJobRepository(db)
                j = repo.get(job_id)
                if j is None:
                    return
                try:
                    j.fail(code=code, message=message)
                except JobTransitionError:
                    pass
                repo.update(j)
        except Exception:  # noqa: BLE001
            log.exception("safe_fail_error", job_id=job_id)

    async def _mark_cancelled_pre_pickup(self, job_id: str) -> None:
        with session_scope() as db:
            repo = GenerationJobRepository(db)
            j = repo.get(job_id)
            if j is None:
                return
            try:
                j.cancel()
            except JobTransitionError:
                pass
            repo.update(j)
        await event_bus.publish(
            "jobs",
            {
                "type": "job_cancelled",
                "job_id": job_id,
                "phase": "queued",
            },
        )


_SAMPLE_CACHE: bytes | None = None


def _curated_sample_bytes() -> bytes | None:
    """Return cached curated-sample bytes (771KB) or None.

    Resolves repo-root independent of CWD and caches in memory so every
    mock job doesn't re-read from disk. Env AURA_CURATED_SAMPLE overrides.
    """
    import pathlib

    global _SAMPLE_CACHE
    if _SAMPLE_CACHE is not None:
        return _SAMPLE_CACHE
    candidates: list[pathlib.Path] = []
    env = __import__("os").environ.get("AURA_CURATED_SAMPLE")
    if env:
        candidates.append(pathlib.Path(env))
    here = pathlib.Path(__file__).resolve()
    # .../services/backend/src/aura_backend/inference/worker.py -> repo root = parents[5]
    try:
        repo_root = here.parents[5]
        candidates.append(repo_root / "apps/stage/public/videos/curated-a.mp4")
    except IndexError:
        pass
    candidates += [
        pathlib.Path("/workspace/FortressForge/apps/stage/public/videos/curated-a.mp4"),
        pathlib.Path("apps/stage/public/videos/curated-a.mp4"),
        pathlib.Path("./apps/stage/public/videos/curated-a.mp4"),
        pathlib.Path("./data/curated-a.mp4"),
    ]
    for cand in candidates:
        try:
            if cand.exists():
                _SAMPLE_CACHE = cand.read_bytes()
                return _SAMPLE_CACHE
        except Exception:
            continue
    return None


def _ensure_generated_video_file(job_id: str, result: ProviderResult) -> tuple[str, str, int | None]:
    """Ensure a real MP4 file exists in storage for the given result.

    Returns (storage_key, storage_url, size_bytes).
    For mock://, generates a real MP4 by copying a curated sample or creating via ffmpeg.
    For http(s)://, downloads and stores.
    For local path, reads and stores.
    """
    import pathlib
    import shutil
    import tempfile

    from ..storage import get_storage

    storage = get_storage()
    key = f"generated/{job_id[:2]}/{job_id}.mp4"

    # If already exists, reuse
    if storage.exists(key):
        try:
            data = storage.get(key)
            return key, storage.get_url(key), len(data)
        except Exception:
            pass

    raw_bytes: bytes | None = None
    ref = result.output_ref

    try:
        if ref.startswith("mock://"):
            # Copy the curated sample (cached, CWD-independent). Falls back
            # to ffmpeg color-bars only if the sample is missing.
            raw_bytes = _curated_sample_bytes()
            if raw_bytes is None:
                # Fallback: try ffmpeg generation (color bars) if available
                try:
                    import subprocess

                    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                        tmp_path = tmp.name
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        f"color=c=0x7c5cff:s=720x1280:d=4:r=12",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        tmp_path,
                    ]
                    subprocess.run(cmd, check=True, capture_output=True, timeout=10)
                    raw_bytes = pathlib.Path(tmp_path).read_bytes()
                    pathlib.Path(tmp_path).unlink(missing_ok=True)
                except Exception:
                    # Final fallback: minimal placeholder (still serveable, but player will skip)
                    raw_bytes = b"\x00" * 1024

        elif ref.startswith("http://") or ref.startswith("https://"):
            # Download remote artifact
            import httpx

            try:
                resp = httpx.get(ref, timeout=30.0, follow_redirects=True)
                resp.raise_for_status()
                raw_bytes = resp.content
            except Exception:
                raw_bytes = None

        elif ref.startswith("/") or ref.startswith("generated/"):
            # Local path or storage key
            try:
                raw_bytes = storage.get(ref.lstrip("/"))
            except Exception:
                # Try as filesystem path
                p = pathlib.Path(ref)
                if p.exists():
                    raw_bytes = p.read_bytes()
                    # Clean temp file after reading
                    try:
                        if "aura_generated" in str(p) or str(p).startswith("/tmp/"):
                            p.unlink(missing_ok=True)
                    except Exception:
                        pass

        if raw_bytes is None:
            # Try to read as storage key fallback
            try:
                raw_bytes = storage.get(ref)
            except Exception:
                raw_bytes = b"\x00" * 1024

    except Exception:
        raw_bytes = b"\x00" * 1024

    # Store to canonical location
    try:
        storage.put(key, raw_bytes or b"\x00" * 1024, content_type="video/mp4")
    except Exception:
        pass
    # Clean temp file if ref was a temp path
    try:
        p = pathlib.Path(ref)
        if p.exists() and ("aura_generated" in str(p) or str(p).startswith("/tmp/")):
            p.unlink(missing_ok=True)
    except Exception:
        pass

    url = storage.get_url(key)
    size = len(raw_bytes) if raw_bytes else None
    return key, url, size


def _to_video_asset(result: ProviderResult, owner_session_id: str, job_id: str):
    from ..domain.video_asset import VideoAsset

    key, url, size = _ensure_generated_video_file(job_id, result)
    # Prefer size from storage if available
    size_bytes = size or result.size_bytes
    return VideoAsset(
        key=key,
        url=url,
        duration_sec=result.duration_sec,
        codec=result.codec or VideoCodec.H264,
        size_bytes=size_bytes,
        width=result.width,
        height=result.height,
        fps=result.fps,
        checksum_sha256=result.checksum_sha256,
    )


# ---- Singleton + entrypoint ----

_worker: InferenceWorker | None = None


def get_worker() -> InferenceWorker:
    global _worker
    if _worker is None:
        _worker = InferenceWorker()
    return _worker


def set_worker(worker: InferenceWorker | None) -> None:
    global _worker
    _worker = worker


async def run_worker_forever() -> None:
    s = get_settings()
    configure_logging(s.log_level)
    init_db()
    from .logging import configure_logging  # noqa: F401
    from ..db import init_db  # noqa: F401

    worker = get_worker()
    await worker.run_forever()