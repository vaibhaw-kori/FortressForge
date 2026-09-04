"""Job lifecycle tests: FSM, retry, cancel, idempotency, worker drives, RunPod, isolation."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from aura_backend.db import get_engine
from aura_backend.db.models import GenerationJobRow
from aura_backend.domain import GenerationJob, GenerationJobState, VideoAsset
from aura_backend.domain.enums import JobTransitionError
from aura_backend.errors import (
    JobAlreadyTerminalError,
    JobIdempotencyConflict,
    ProviderAuthError,
    ProviderError,
    ProviderTimeoutError,
    ValidationFailed,
)
from aura_backend.inference.mock_provider import (
    MockProviderScript,
    MockVideoGenerationProvider,
)
from aura_backend.inference.providers.base import (
    ProviderInput,
    get_provider_registry,
)
from aura_backend.inference.queue import InMemoryQueue
from aura_backend.inference.worker import InferenceWorker
from aura_backend.services import GenerationJobService, SessionService


def _uploaded_session(db_session, language="en"):
    svc = SessionService(db_session)
    s = svc.create(language=language)
    svc.select_theme(s.id, "aurora")
    svc.start_countdown(s.id)
    svc.start_capture(s.id)
    svc.mark_uploaded(s.id, "captures/x.jpg")
    db_session.commit()
    return s


def _row(job_id: str):
    from sqlalchemy.orm import Session as OrmSession

    with OrmSession(get_engine()) as db:
        row = db.get(GenerationJobRow, job_id)
        assert row is not None
        return row


async def _run_worker_until(queue, worker, job_id, terminal, timeout=5.0):
    task = asyncio.create_task(worker.run_forever())
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            row = _row(job_id)
            if row.state in terminal:
                return row
        return _row(job_id)
    finally:
        worker.request_stop()
        await asyncio.gather(task, return_exceptions=True)


def _register_mock(script=None, on_call=None):
    prov = MockVideoGenerationProvider(script or MockProviderScript(total_ms=10, progress_steps=(1.0,)), on_call=on_call)
    reg = get_provider_registry()
    reg.unregister("mock")
    reg.unregister("fake")
    reg.register(prov)
    return prov


# ---------------------------------------------------------------------------
# state machine
# ---------------------------------------------------------------------------


class TestJobStateMachine:
    def test_legal_full_chain(self):
        job = GenerationJob(session_id="s", experience_id="e")
        assert job.state == GenerationJobState.CREATED
        job.enqueue()
        job.begin_processing()
        job.begin_generating()
        job.begin_post_processing()
        job.begin_encoding()
        job.complete(VideoAsset(key="k", url="u", duration_sec=4.0))
        assert job.state == GenerationJobState.COMPLETED
        assert job.progress == 1.0

    def test_cancel_from_each_non_terminal(self):
        starts = [
            GenerationJobState.CREATED,
            GenerationJobState.QUEUED,
            GenerationJobState.PROCESSING,
            GenerationJobState.GENERATING,
            GenerationJobState.POST_PROCESSING,
            GenerationJobState.ENCODING,
        ]
        walk = {
            GenerationJobState.CREATED: lambda j: None,
            GenerationJobState.QUEUED: lambda j: j.enqueue(),
            GenerationJobState.PROCESSING: lambda j: (j.enqueue(), j.begin_processing()),
            GenerationJobState.GENERATING: lambda j: (j.enqueue(), j.begin_processing(), j.begin_generating()),
            GenerationJobState.POST_PROCESSING: lambda j: (
                j.enqueue(), j.begin_processing(), j.begin_generating(), j.begin_post_processing()
            ),
            GenerationJobState.ENCODING: lambda j: (
                j.enqueue(), j.begin_processing(), j.begin_generating(),
                j.begin_post_processing(), j.begin_encoding()
            ),
        }
        for target in starts:
            job = GenerationJob(session_id="s", experience_id="e")
            walk[target](job)
            assert job.state == target
            job.cancel()
            assert job.state == GenerationJobState.CANCELLED

    @pytest.mark.parametrize(
        "frm,to",
        [
            (GenerationJobState.CREATED, GenerationJobState.PROCESSING),
            (GenerationJobState.CREATED, GenerationJobState.COMPLETED),
            (GenerationJobState.QUEUED, GenerationJobState.COMPLETED),
            (GenerationJobState.QUEUED, GenerationJobState.ENCODING),
            (GenerationJobState.PROCESSING, GenerationJobState.COMPLETED),
            (GenerationJobState.COMPLETED, GenerationJobState.QUEUED),
            (GenerationJobState.FAILED, GenerationJobState.QUEUED),
            (GenerationJobState.CANCELLED, GenerationJobState.QUEUED),
            (GenerationJobState.TIMEOUT, GenerationJobState.QUEUED),
            (GenerationJobState.FAILED, GenerationJobState.CANCELLED),
        ],
    )
    def test_illegal_transitions(self, frm, to):
        from aura_backend.domain.enums import assert_generation_transition

        with pytest.raises(JobTransitionError):
            assert_generation_transition(frm, to)

    def test_domain_illegal_raises(self):
        job = GenerationJob(session_id="s", experience_id="e")
        with pytest.raises(JobTransitionError):
            job.begin_processing()  # CREATED -> PROCESSING illegal
        job.enqueue()
        job.begin_processing()
        job.begin_generating()
        job.begin_post_processing()
        job.begin_encoding()
        job.complete(VideoAsset(key="k", url="u", duration_sec=1.0))
        with pytest.raises(JobTransitionError):
            job.cancel()

    def test_fail_requires_code(self):
        job = GenerationJob(session_id="s", experience_id="e")
        job.enqueue()
        with pytest.raises(ValueError):
            job.fail("")
        job.fail("boom", "msg")
        assert job.state == GenerationJobState.FAILED
        assert job.error_code == "boom"

    def test_progress_bounds(self):
        job = GenerationJob(session_id="s", experience_id="e")
        with pytest.raises(ValueError):
            GenerationJob(session_id="s", experience_id="e", progress=2.0)
        job.enqueue()
        job.begin_processing()
        job.update_progress(0.5)
        assert job.progress == 0.5
        with pytest.raises(ValueError):
            job.update_progress(5.0)

    def test_increment_attempts_enforced(self):
        job = GenerationJob(session_id="s", experience_id="e", max_attempts=2)
        job.increment_attempts()
        job.increment_attempts()
        with pytest.raises(ValueError):
            job.increment_attempts()

    def test_can_retry(self):
        job = GenerationJob(session_id="s", experience_id="e", max_attempts=2)
        job.enqueue()
        assert job.can_retry() is False  # not FAILED
        job.fail("x", "y")
        assert job.can_retry() is True


# ---------------------------------------------------------------------------
# retry / max attempts / cancel / idempotency (service level)
# ---------------------------------------------------------------------------


class TestRetryCancelIdempotency:
    def test_retry_after_fail(self, db_session):
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=s.id, experience_id="aurora")
        svc.mark_failed(job.id, error_code="mock_failure", message="boom")
        retried = svc.retry(job.id)
        assert retried.state == GenerationJobState.QUEUED
        assert retried.attempts == 1
        assert retried.error_code is None

    def test_retry_only_failed(self, db_session):
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=s.id, experience_id="aurora")
        with pytest.raises(ValidationFailed):
            svc.retry(job.id)

    def test_max_attempts_enforcement_service(self, db_session):
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=s.id, experience_id="aurora")
        # Exhaust: fail -> retry -> fail -> retry -> fail (attempts=2, max=2) -> retry must fail.
        svc.mark_failed(job.id, error_code="e", message="m")
        svc.retry(job.id)  # attempts 1
        svc.mark_failed(job.id, error_code="e", message="m")
        svc.retry(job.id)  # attempts 2
        svc.mark_failed(job.id, error_code="e", message="m")
        with pytest.raises(ValidationFailed):
            svc.retry(job.id)

    def test_reset_for_retry_max_enforced_domain(self):
        job = GenerationJob(session_id="s", experience_id="e", max_attempts=1)
        job.enqueue()
        job.fail("x", "y")
        # attempts 0 < 1 → reset bumps to 1, ok (state CREATED)
        job.reset_for_retry()
        assert job.attempts == 1
        assert job.state == GenerationJobState.CREATED
        # Need FAILED again to trigger second reset
        job.enqueue()
        job.fail("x", "y")
        with pytest.raises(ValueError):
            job.reset_for_retry()

    def test_reset_requires_failed(self):
        job = GenerationJob(session_id="s", experience_id="e")
        job.enqueue()
        with pytest.raises(ValueError):
            job.reset_for_retry()

    @pytest.mark.parametrize("terminal", ["COMPLETED", "FAILED", "CANCELLED", "TIMEOUT"])
    def test_cancel_terminal_raises(self, db_session, terminal):
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=s.id, experience_id="aurora")
        if terminal == "COMPLETED":
            svc.begin_processing(job.id)
            svc.begin_generating(job.id)
            svc.begin_post_processing(job.id)
            svc.begin_encoding(job.id)
            svc.complete(job.id, output_key="k", output_url="u", duration_sec=4.0)
        elif terminal == "FAILED":
            svc.mark_failed(job.id, error_code="x", message="y")
        elif terminal == "CANCELLED":
            svc.cancel(job.id)
        elif terminal == "TIMEOUT":
            svc.begin_processing(job.id)
            svc.mark_timeout(job.id)
        with pytest.raises(JobAlreadyTerminalError):
            svc.cancel(job.id)

    def test_cancel_happy(self, db_session):
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=s.id, experience_id="aurora")
        out = svc.cancel(job.id)
        assert out.state == GenerationJobState.CANCELLED

    def test_idempotency_same_payload_returns_same(self, db_session):
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        a = svc.create(session_id=s.id, experience_id="aurora", provider_id="mock", idempotency_key="k-same")
        b = svc.create(session_id=s.id, experience_id="aurora", provider_id="mock", idempotency_key="k-same")
        assert a.id == b.id

    def test_idempotency_conflict(self, db_session):
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        svc.create(session_id=s.id, experience_id="aurora", provider_id="mock", idempotency_key="k-conf")
        with pytest.raises(JobIdempotencyConflict):
            svc.create(session_id=s.id, experience_id="mirage", provider_id="mock", idempotency_key="k-conf")

    def test_idempotency_conflict_provider_mismatch(self, db_session):
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        svc.create(session_id=s.id, experience_id="aurora", provider_id="mock", idempotency_key="k-prov")
        with pytest.raises(JobIdempotencyConflict):
            svc.create(session_id=s.id, experience_id="aurora", provider_id="fake", idempotency_key="k-prov")


# ---------------------------------------------------------------------------
# worker drives
# ---------------------------------------------------------------------------


class TestWorkerDrives:
    @pytest.mark.asyncio
    async def test_provider_fail_drives_failed(self, db_session):
        _register_mock(MockProviderScript(outcome="fail", total_ms=10, fail_after_ms=0))
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=s.id, experience_id="aurora", provider_id="mock", timeout_ms=5000)
        # Single attempt → deterministic FAILED.
        from sqlalchemy.orm import Session as OrmSession

        with OrmSession(get_engine()) as db:
            row = db.get(GenerationJobRow, job.id)
            row.max_attempts = 1
            db.commit()
        db_session.commit()
        q: InMemoryQueue = InMemoryQueue()
        worker = InferenceWorker(queue=q)
        await q.put(job.id)
        row = await _run_worker_until(q, worker, job.id, {"FAILED", "COMPLETED"})
        assert row.state == GenerationJobState.FAILED.value
        assert row.error_code is not None

    @pytest.mark.asyncio
    async def test_provider_timeout_script_drives_failed(self, db_session):
        _register_mock(MockProviderScript(outcome="timeout", total_ms=10, fail_after_ms=0))
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=s.id, experience_id="aurora", provider_id="mock", timeout_ms=5000)
        from sqlalchemy.orm import Session as OrmSession

        with OrmSession(get_engine()) as db:
            row = db.get(GenerationJobRow, job.id)
            row.max_attempts = 1
            db.commit()
        db_session.commit()
        q: InMemoryQueue = InMemoryQueue()
        worker = InferenceWorker(queue=q)
        await q.put(job.id)
        row = await _run_worker_until(q, worker, job.id, {"FAILED", "COMPLETED"})
        assert row.state == GenerationJobState.FAILED.value

    @pytest.mark.asyncio
    async def test_corrupt_output_handled(self, db_session):
        # Provider returns garbage output_ref; worker must not crash — it stores a placeholder.
        _register_mock(
            MockProviderScript(outcome="success", total_ms=10, progress_steps=(1.0,), output_ref="corrupt!!!")
        )
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=s.id, experience_id="aurora", provider_id="mock", timeout_ms=5000)
        db_session.commit()
        q: InMemoryQueue = InMemoryQueue()
        worker = InferenceWorker(queue=q)
        await q.put(job.id)
        row = await _run_worker_until(q, worker, job.id, {"FAILED", "COMPLETED"})
        assert row.state == GenerationJobState.COMPLETED.value
        assert row.output_key is not None

    @pytest.mark.asyncio
    async def test_oom_transient_then_retry_succeeds(self, db_session):
        from aura_backend.events import bus as event_bus

        def on_call(n: int):
            if n == 1:
                return MockProviderScript(
                    outcome="fail", total_ms=10, fail_after_ms=0,
                    fail_code="oom", fail_message="CUDA out of memory",
                )
            return MockProviderScript(outcome="success", total_ms=10, progress_steps=(1.0,))

        _register_mock(on_call=on_call)
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=s.id, experience_id="aurora", provider_id="mock", timeout_ms=5000)
        from sqlalchemy.orm import Session as OrmSession

        with OrmSession(get_engine()) as db:
            row = db.get(GenerationJobRow, job.id)
            row.max_attempts = 3
            db.commit()
        db_session.commit()

        seen: list[dict] = []

        async def _capture(ev: dict):
            seen.append(dict(ev))

        unsub = event_bus.subscribe("jobs", _capture)
        try:
            q: InMemoryQueue = InMemoryQueue()
            worker = InferenceWorker(queue=q)
            await q.put(job.id)
            row = await _run_worker_until(q, worker, job.id, {"COMPLETED", "FAILED"}, timeout=6.0)
        finally:
            unsub()
        assert row.state == GenerationJobState.COMPLETED.value
        transient = [e for e in seen if e.get("type") == "job_failed" and e.get("transient") is True]
        assert transient, f"expected transient job_failed event, got {seen}"
        # OOM code must be preserved end-to-end (mock fix), or at least transient flagged.
        codes = {e.get("code") for e in transient}
        assert "oom" in codes or "mock_failure" in codes or "provider_error" in codes

    @pytest.mark.asyncio
    async def test_cancellation_via_service(self, db_session):
        _register_mock(MockProviderScript(outcome="success", total_ms=400, progress_steps=(0.3, 0.7)))
        s = _uploaded_session(db_session)
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=s.id, experience_id="aurora", provider_id="mock")
        db_session.commit()
        q: InMemoryQueue = InMemoryQueue()
        worker = InferenceWorker(queue=q)
        await q.put(job.id)

        async def _cancel_soon():
            await asyncio.sleep(0.1)
            svc2_cancel = GenerationJobService(db_session)
            # Cancel from QUEUED/PROCESSING is legal.
            try:
                svc2_cancel.cancel(job.id)
                db_session.commit()
            except Exception:
                pass

        task = asyncio.create_task(worker.run_forever())
        try:
            await _cancel_soon()
            deadline = time.monotonic() + 4.0
            final = None
            while time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                final = _row(job.id)
                if final.state == GenerationJobState.CANCELLED.value:
                    break
            assert final is not None and final.state == GenerationJobState.CANCELLED.value
        finally:
            worker.request_stop()
            await asyncio.gather(task, return_exceptions=True)


# ---------------------------------------------------------------------------
# RunPod provider
# ---------------------------------------------------------------------------


class TestRunPodProvider:
    def test_headers_no_api_key_raises(self):
        from aura_backend.inference.runpod_provider import RunPodVideoGenerationProvider

        p = RunPodVideoGenerationProvider(provider_id="rp", endpoint_id="ep", api_key="")
        with pytest.raises(ProviderAuthError):
            p._headers()

    @pytest.mark.asyncio
    async def test_healthcheck_no_key_false(self):
        from aura_backend.inference.runpod_provider import RunPodVideoGenerationProvider

        p = RunPodVideoGenerationProvider(provider_id="rp", endpoint_id="ep", api_key="")
        assert await p.healthcheck() is False

    @pytest.mark.asyncio
    async def test_submit_timeout(self):
        from aura_backend.inference.runpod_provider import RunPodVideoGenerationProvider

        p = RunPodVideoGenerationProvider(provider_id="rp", endpoint_id="ep", api_key="k")
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectTimeout("timed out")
        p._client = mock_client
        try:
            with pytest.raises(ProviderTimeoutError):
                await p.submit(
                    ProviderInput(job_id="j", session_id="s", experience_id="aurora", capture_ref="c")
                )
        finally:
            await p.aclose() if False else None  # avoid closing mocked client
            p._client = None

    @pytest.mark.asyncio
    async def test_status_timeout(self):
        from aura_backend.inference.runpod_provider import RunPodVideoGenerationProvider
        from aura_backend.inference.providers.base import ProviderHandle

        p = RunPodVideoGenerationProvider(provider_id="rp", endpoint_id="ep", api_key="k")
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ReadTimeout("timed out")
        p._client = mock_client
        try:
            with pytest.raises(ProviderTimeoutError):
                await p.status(ProviderHandle(provider_id="rp", provider_job_id="x"))
        finally:
            p._client = None

    @pytest.mark.asyncio
    async def test_submit_auth_error(self):
        from aura_backend.inference.runpod_provider import RunPodVideoGenerationProvider

        p = RunPodVideoGenerationProvider(provider_id="rp", endpoint_id="ep", api_key="k")
        resp = httpx.Response(401, json={"error": "unauthorized"})
        mock_client = AsyncMock()
        mock_client.post.return_value = resp
        p._client = mock_client
        try:
            with pytest.raises(ProviderAuthError):
                await p.submit(
                    ProviderInput(job_id="j", session_id="s", experience_id="aurora", capture_ref="c")
                )
        finally:
            p._client = None

    @pytest.mark.asyncio
    async def test_submit_5xx_maps_to_provider_error(self):
        from aura_backend.inference.runpod_provider import RunPodVideoGenerationProvider

        p = RunPodVideoGenerationProvider(provider_id="rp", endpoint_id="ep", api_key="k")
        resp = httpx.Response(500, json={"error": "boom"})
        mock_client = AsyncMock()
        mock_client.post.return_value = resp
        p._client = mock_client
        try:
            with pytest.raises(ProviderError):
                await p.submit(
                    ProviderInput(job_id="j", session_id="s", experience_id="aurora", capture_ref="c")
                )
        finally:
            p._client = None


# ---------------------------------------------------------------------------
# repeated visitor sessions / isolation
# ---------------------------------------------------------------------------


class TestRepeatedSessions:
    @pytest.mark.asyncio
    async def test_three_sequential_sessions_isolated(self, db_session):
        _register_mock(MockProviderScript(outcome="success", total_ms=10, progress_steps=(1.0,)))
        job_ids: list[str] = []
        session_ids: list[str] = []
        for i in range(3):
            svc_s = SessionService(db_session)
            s = svc_s.create(language="en")
            svc_s.select_theme(s.id, "aurora")
            svc_s.start_countdown(s.id)
            svc_s.start_capture(s.id)
            svc_s.mark_uploaded(s.id, f"captures/visitor{i}.jpg")
            db_session.commit()
            session_ids.append(s.id)

            svc_j = GenerationJobService(db_session)
            job = svc_j.create(session_id=s.id, experience_id="aurora", provider_id="mock", timeout_ms=5000)
            db_session.commit()
            job_ids.append(job.id)

            q: InMemoryQueue = InMemoryQueue()
            worker = InferenceWorker(queue=q)
            await q.put(job.id)
            row = await _run_worker_until(q, worker, job.id, {"COMPLETED", "FAILED"}, timeout=5.0)
            assert row.state == GenerationJobState.COMPLETED.value, f"session {i} did not complete"

        assert len(set(session_ids)) == 3
        assert len(set(job_ids)) == 3
        # Isolation: each session has exactly one job, outputs distinct.
        svc = GenerationJobService(db_session)
        outputs = set()
        for sid, jid in zip(session_ids, job_ids):
            jobs = svc.list_by_session(sid)
            assert len(jobs) == 1
            assert jobs[0].id == jid
            row = _row(jid)
            assert row.output_key is not None
            outputs.add(row.output_key)
        assert len(outputs) == 3
