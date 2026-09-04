"""GenerationJob service.

Layered on top of the domain aggregate and repository. Responsible for:
- Validated creation (with optional idempotency key)
- State transitions (delegated to domain)
- Cancellation (DB-level)
- Retry (idempotent reset_for_retry)
- Provider lookup
- WS event emission via the internal event bus
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session as as_session

from ..config import get_settings
from ..domain import GenerationJob, GenerationJobState, VideoAsset, VideoCodec
from ..events import bus as event_bus
from ..errors import (
    JobAlreadyTerminalError,
    JobIdempotencyConflict,
    JobNotFoundError,
    NotFoundError,
    ValidationFailed,
)
from ..inference.providers.base import get_provider_registry
from ..repositories import GenerationJobRepository, SessionRepository
from ..realtime.hub import envelope


class GenerationJobService:
    def __init__(self, db) -> None:
        self._db = db
        self._repo = GenerationJobRepository(db)
        self._sessions = SessionRepository(db)

    # ---- creation ----

    def create(
        self,
        session_id: str,
        experience_id: str,
        *,
        provider_id: str | None = None,
        idempotency_key: str | None = None,
        timeout_ms: int | None = None,
    ) -> GenerationJob:
        s = get_settings()
        settings_provider = s.runpod_provider_default
        settings_timeout = s.generation_timeout_ms

        session = self._sessions.get(session_id)
        if session is None:
            raise NotFoundError(f"Session {session_id} not found")
        if not session.capture_ref:
            raise ValidationFailed("Session has no capture uploaded yet")
        if not experience_id:
            raise ValidationFailed("experience_id required")

        chosen_provider = provider_id or settings_provider
        registry = get_provider_registry()
        if not registry.has(chosen_provider):
            raise ValidationFailed(f"unknown provider: {chosen_provider}")

        # Idempotency: if a key was supplied and we already have a job for it,
        # return that job (ensuring the same payload).
        if idempotency_key:
            existing = self._repo.find_by_idempotency_key(idempotency_key)
            if existing is not None:
                if (
                    existing.session_id != session_id
                    or existing.experience_id != experience_id
                    or existing.provider_id != chosen_provider
                ):
                    raise JobIdempotencyConflict(
                        "idempotency_key reused with different payload",
                        details={
                            "idempotency_key": idempotency_key,
                            "existing_job_id": existing.id,
                        },
                    )
                return existing

        job = GenerationJob(
            session_id=session_id,
            experience_id=experience_id,
            provider_id=chosen_provider,
            max_attempts=max(1, s.generation_max_attempts),
            input_ref=session.capture_ref,
            idempotency_key=idempotency_key,
            timeout_ms=timeout_ms or settings_timeout,
        )
        job.enqueue()  # CREATED -> QUEUED
        self._repo.add(job)

        # Reflect session transition into GENERATING (no DB-level guard against
        # running it twice; session FSM enforces).
        if session.state.value == "UPLOADED":
            try:
                session.mark_generating()
                self._sessions.update(session)
            except Exception:  # noqa: BLE001
                pass

        # Emit job_created + job_queued
        self._emit(
            "job_created",
            job_id=job.id,
            session_id=job.session_id,
            experience_id=job.experience_id,
            provider_id=job.provider_id,
            created_at=job.created_at.isoformat(),
        )
        self._emit(
            "job_queued",
            job_id=job.id,
            session_id=job.session_id,
        )

        return job

    # ---- read ----

    def get(self, job_id: str) -> GenerationJob:
        job = self._repo.get(job_id)
        if job is None:
            raise JobNotFoundError(f"Job {job_id} not found")
        return job

    def list(self) -> list[GenerationJob]:
        return self._repo.list()

    def list_by_session(self, session_id: str) -> list[GenerationJob]:
        return self._repo.list_by_session(session_id)

    def find_by_idempotency_key(self, key: str) -> GenerationJob | None:
        return self._repo.find_by_idempotency_key(key)

    # ---- state transitions ----

    def cancel(self, job_id: str) -> GenerationJob:
        job = self.get(job_id)
        if job.state in (
            GenerationJobState.COMPLETED,
            GenerationJobState.CANCELLED,
            GenerationJobState.TIMEOUT,
        ):
            raise JobAlreadyTerminalError(
                f"Job {job_id} is already in terminal state {job.state.value}",
                details={"state": job.state.value},
            )
        job.cancel()
        self._repo.update(job)
        self._emit(
            "job_cancelled",
            job_id=job.id,
            session_id=job.session_id,
            state=job.state.value,
        )
        return job

    def fail(self, job_id: str, code: str, message: str | None = None) -> GenerationJob:
        return self.mark_failed(job_id, error_code=code, message=message)

    def timeout(self, job_id: str) -> GenerationJob:
        return self.mark_timeout(job_id)

    def retry(self, job_id: str) -> GenerationJob:
        job = self.get(job_id)
        if job.state != GenerationJobState.FAILED:
            raise ValidationFailed(
                f"Only FAILED jobs can be retried (got {job.state.value})"
            )
        if not job.can_retry():
            raise ValidationFailed("Job has no retry attempts remaining")
        job.reset_for_retry()
        job.enqueue()
        self._repo.update(job)
        self._emit(
            "job_retry",
            job_id=job.id,
            session_id=job.session_id,
            attempts=job.attempts,
        )
        self._emit("job_queued", job_id=job.id, session_id=job.session_id)
        return job

    def mark_failed(self, job_id: str, *, error_code: str, message: str | None = None) -> GenerationJob:
        job = self.get(job_id)
        job.fail(code=error_code, message=message)
        self._repo.update(job)
        self._emit(
            "job_failed",
            job_id=job.id,
            session_id=job.session_id,
            code=error_code,
            message=message,
        )
        return job

    def mark_timeout(self, job_id: str) -> GenerationJob:
        job = self.get(job_id)
        job.timeout()
        self._repo.update(job)
        self._emit(
            "job_failed",
            job_id=job.id,
            session_id=job.session_id,
            code="timeout",
            message="watchdog timeout",
        )
        return job

    def update_progress(self, job_id: str, progress: float) -> GenerationJob:
        job = self.get(job_id)
        job.update_progress(progress)
        self._repo.update(job)
        self._emit(
            "job_progress",
            job_id=job.id,
            session_id=job.session_id,
            progress=progress,
            state=job.state.value,
        )
        return job

    # ---- FSM helpers (used by worker + tests) ----

    def begin_processing(self, job_id: str) -> GenerationJob:
        job = self.get(job_id)
        job.begin_processing()
        return self._repo.update(job)

    def begin_generating(self, job_id: str) -> GenerationJob:
        job = self.get(job_id)
        job.begin_generating()
        return self._repo.update(job)

    def begin_post_processing(self, job_id: str) -> GenerationJob:
        job = self.get(job_id)
        job.begin_post_processing()
        return self._repo.update(job)

    def begin_encoding(self, job_id: str) -> GenerationJob:
        job = self.get(job_id)
        job.begin_encoding()
        return self._repo.update(job)

    def complete(
        self,
        job_id: str,
        *,
        output_key: str,
        output_url: str,
        duration_sec: float,
        codec=VideoCodec.H264,
        size_bytes: int | None = None,
        width: int | None = None,
        height: int | None = None,
        fps: int | None = None,
        checksum_sha256: str | None = None,
    ) -> GenerationJob:
        job = self.get(job_id)
        output = VideoAsset(
            key=output_key,
            url=output_url,
            duration_sec=duration_sec,
            codec=codec,
            size_bytes=size_bytes,
            width=width,
            height=height,
            fps=fps,
            checksum_sha256=checksum_sha256,
        )
        # Walk through the remaining FSM states to honor latencies.
        try:
            job.begin_generating()
        except Exception:  # noqa: BLE001
            pass
        try:
            job.begin_post_processing()
        except Exception:  # noqa: BLE001
            pass
        try:
            job.begin_encoding()
        except Exception:  # noqa: BLE001
            pass
        job.complete(output)
        updated = self._repo.update(job)
        self._emit(
            "job_completed",
            job_id=updated.id,
            session_id=updated.session_id,
            output_ref=updated.output.key if updated.output else None,
            duration_sec=duration_sec,
        )
        return updated

    # ---- helpers ----

    def _emit(self, event_type: str, **fields) -> None:
        # Local in-process bus; the realtime relay translates to WS broadcasts.
        payload = envelope(event_type, **fields)
        # event_bus.publish is async; this is called from sync context.
        # We use asyncio.create_task if a loop is running, otherwise no-op.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(event_bus.publish("jobs", payload))
        except RuntimeError:
            # No loop (e.g. unit tests that don't run the relay). Just enqueue.
            # We still call publish() through asyncio.run to keep the bus consistent.
            try:
                asyncio.get_event_loop().run_until_complete(event_bus.publish("jobs", payload))
            except Exception:  # noqa: BLE001
                pass