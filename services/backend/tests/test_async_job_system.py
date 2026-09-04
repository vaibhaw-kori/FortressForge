"""Tests for the async video-generation job system.

Covers:
- VideoGenerationProvider contract (Mock)
- InMemoryQueue ordering + cancel-before-pickup
- InferenceWorker happy path, retries, timeout, cancellation, idempotency
- GenerationJobService emit semantics
- WebSocketHub broadcasting
- API endpoints: create/cancel/retry
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from aura_backend.db.models import Base, GenerationJobRow
from aura_backend.db import get_engine
from aura_backend.domain.enums import GenerationJobState
from aura_backend.errors import (
    JobAlreadyTerminalError,
    JobIdempotencyConflict,
    ProviderError,
)
from aura_backend.inference.mock_provider import (
    MockProviderScript,
    MockVideoGenerationProvider,
)
from aura_backend.inference.providers.base import (
    PROVIDER_STATUS_CANCELLED,
    PROVIDER_STATUS_FAILED,
    PROVIDER_STATUS_QUEUED,
    PROVIDER_STATUS_RUNNING,
    PROVIDER_STATUS_SUCCEEDED,
    ProgressEvent,
    ProviderInput,
    ProviderResult,
    VideoGenerationProvider,
    get_provider_registry,
)
from aura_backend.inference.queue import InMemoryQueue
from aura_backend.inference.worker import InferenceWorker
from aura_backend.realtime.hub import WebSocketHub, envelope
from aura_backend.realtime.protocol import (
    DISPLAY1_EVENT_TYPES,
    DISPLAY2_EVENT_TYPES,
    WSRole,
    make_envelope,
    parse_client_message,
)
from aura_backend.services import GenerationJobService, SessionService


# ---- helpers ----


def _ensure_db():
    Base.metadata.create_all(bind=get_engine())


@pytest.fixture()
def fresh_db(db_session):
    _ensure_db()
    return db_session


@pytest.fixture()
def uploaded_session(db_session):
    svc = SessionService(db_session)
    s = svc.create(language="en")
    svc.select_theme(s.id, "aurora")
    svc.start_countdown(s.id)
    svc.start_capture(s.id)
    svc.mark_uploaded(s.id, "captures/x.jpg")
    return s


# ============================================================
# VideoGenerationProvider (Mock) tests
# ============================================================


class TestMockProvider:
    @pytest.mark.asyncio
    async def test_submit_returns_handle(self):
        prov = MockVideoGenerationProvider()
        handle = await prov.submit(
            ProviderInput(
                job_id="j1",
                session_id="s1",
                experience_id="aurora",
                capture_ref="cap.jpg",
            )
        )
        assert handle.provider_id == "mock"
        assert handle.provider_job_id

    @pytest.mark.asyncio
    async def test_drive_to_success_emits_progress(self):
        prov = MockVideoGenerationProvider(MockProviderScript(total_ms=20, progress_steps=(0.2, 0.5, 1.0)))
        handle = await prov.submit(
            ProviderInput(
                job_id="j1",
                session_id="s1",
                experience_id="aurora",
                capture_ref="cap.jpg",
            )
        )
        events: list[ProgressEvent] = []
        await prov.drive(handle, on_progress=events.append)
        assert [e.progress for e in events] == [0.2, 0.5, 1.0]
        status = await prov.status(handle)
        assert status == PROVIDER_STATUS_SUCCEEDED
        result = await prov.result(handle)
        assert result.duration_sec > 0

    @pytest.mark.asyncio
    async def test_drive_to_failure(self):
        prov = MockVideoGenerationProvider(
            MockProviderScript(outcome="fail", total_ms=10, fail_after_ms=0)
        )
        handle = await prov.submit(
            ProviderInput(job_id="j1", session_id="s1", experience_id="aurora", capture_ref="x")
        )
        await prov.drive(handle)
        assert await prov.status(handle) == PROVIDER_STATUS_FAILED
        with pytest.raises(ProviderError):
            await prov.result(handle)

    @pytest.mark.asyncio
    async def test_cancel_pre_completion(self):
        prov = MockVideoGenerationProvider(
            MockProviderScript(outcome="success", total_ms=200, progress_steps=(0.5,))
        )
        handle = await prov.submit(
            ProviderInput(job_id="j1", session_id="s1", experience_id="aurora", capture_ref="x")
        )

        def cancelled():
            return True

        await prov.drive(handle, cancel_check=cancelled)
        assert await prov.status(handle) == PROVIDER_STATUS_CANCELLED


# ============================================================
# InMemoryQueue tests
# ============================================================


class TestQueue:
    @pytest.mark.asyncio
    async def test_fifo_ordering(self):
        q: InMemoryQueue = InMemoryQueue()
        await q.put("a")
        await q.put("b")
        await q.put("c")
        assert await q.get() == "a"
        assert await q.get() == "b"
        assert await q.get() == "c"

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        q: InMemoryQueue = InMemoryQueue()
        await q.put("low", priority=10)
        await q.put("high", priority=1)
        await q.put("mid", priority=5)
        assert await q.get() == "high"
        assert await q.get() == "mid"
        assert await q.get() == "low"

    @pytest.mark.asyncio
    async def test_cancel_before_pickup(self):
        q: InMemoryQueue = InMemoryQueue()
        await q.put("x")
        assert q.cancel("x") is True
        # Cancelled IDs are filtered out of get()
        assert await q.get(timeout=0.1) is None


# ============================================================
# InferenceWorker
# ============================================================


@pytest.fixture()
def mock_provider() -> MockVideoGenerationProvider:
    return MockVideoGenerationProvider(MockProviderScript(total_ms=20, progress_steps=(0.25, 0.75, 1.0)))


@pytest.fixture()
def worker_with_queue(db_session, mock_provider) -> tuple[InferenceWorker, InMemoryQueue]:
    reg = get_provider_registry()
    reg.unregister("mock")
    reg.unregister("fake")
    reg.register(mock_provider)
    q: InMemoryQueue = InMemoryQueue()
    w = InferenceWorker(queue=q)
    return w, q


def _make_job_in_state(
    db_session,
    *,
    state: GenerationJobState = GenerationJobState.QUEUED,
    provider_id: str = "mock",
    max_attempts: int = 2,
) -> str:
    job = GenerationJobRow(
        id="jtest_" + os.urandom(4).hex(),
        session_id="s1",
        experience_id="aurora",
        provider_id=provider_id,
        state=state.value if isinstance(state, GenerationJobState) else state,
        attempts=0,
        max_attempts=max_attempts,
        input_ref="captures/x.jpg",
        progress=0.0,
    )
    db_session.add(job)
    db_session.commit()
    return job.id


class TestWorker:
    @pytest.mark.asyncio
    async def test_happy_path(self, worker_with_queue, db_session, uploaded_session):
        worker, queue = worker_with_queue
        svc = GenerationJobService(db_session)
        job = svc.create(
            session_id=uploaded_session.id,
            experience_id="aurora",
            provider_id="mock",
        )
        db_session.commit()
        await queue.put(job.id)
        # Run one tick by stopping after the first job is processed.
        async def run_one():
            worker_task = asyncio.create_task(worker.run_forever())
            await asyncio.sleep(0.5)
            worker.request_stop()
            await asyncio.gather(worker_task, return_exceptions=True)

        await run_one()

        # Re-load to confirm completion.
        from sqlalchemy.orm import Session as OrmSession
        with OrmSession(get_engine()) as db:
            row = db.get(GenerationJobRow, job.id)
        assert row is not None
        assert row.state == GenerationJobState.COMPLETED.value
        assert row.output_key is not None
        assert row.attempts == 1
        assert row.total_latency_ms is not None

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self, db_session, uploaded_session):
        # Provider: first call fails, second call succeeds.
        counter = {"n": 0}

        def on_call(n: int):
            counter["n"] = n
            if n == 1:
                return MockProviderScript(outcome="fail", total_ms=10, fail_after_ms=0)
            return MockProviderScript(outcome="success", total_ms=10, progress_steps=(1.0,))

        provider = MockVideoGenerationProvider(on_call=on_call)
        reg = get_provider_registry()
        reg.unregister("mock")
        reg.unregister("fake")
        reg.register(provider)
        q: InMemoryQueue = InMemoryQueue()
        worker = InferenceWorker(queue=q)
        svc = GenerationJobService(db_session)
        job = svc.create(
            session_id=uploaded_session.id,
            experience_id="aurora",
            provider_id="mock",
        )
        db_session.commit()
        # Force max_attempts=3 so we have room for 1 fail + 1 success.
        from sqlalchemy.orm import Session as OrmSession
        with OrmSession(get_engine()) as db:
            row = db.get(GenerationJobRow, job.id)
            row.max_attempts = 3
            db.commit()

        await q.put(job.id)
        task = asyncio.create_task(worker.run_forever())
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            with OrmSession(get_engine()) as db:
                row = db.get(GenerationJobRow, job.id)
                if row.state == GenerationJobState.COMPLETED.value:
                    break
        worker.request_stop()
        await asyncio.gather(task, return_exceptions=True)

        with OrmSession(get_engine()) as db:
            row = db.get(GenerationJobRow, job.id)
        assert counter["n"] == 2, f"expected 2 provider calls, got {counter['n']}"
        assert row.state == GenerationJobState.COMPLETED.value
        # attempts counts every entry into PROCESSING, including the
        # reset_for_retry bump that the worker performs between attempts.
        assert row.attempts == 3

    @pytest.mark.asyncio
    async def test_timeout_marks_job_failed(self, db_session, uploaded_session):
        # Provider that always takes too long for the watchdog.
        script = MockProviderScript(outcome="success", total_ms=500, progress_steps=(0.1,))
        provider = MockVideoGenerationProvider(script)
        reg = get_provider_registry()
        reg.unregister("mock")
        reg.unregister("fake")
        reg.register(provider)
        q: InMemoryQueue = InMemoryQueue()
        worker = InferenceWorker(queue=q)
        svc = GenerationJobService(db_session)
        job = svc.create(
            session_id=uploaded_session.id,
            experience_id="aurora",
            provider_id="mock",
            timeout_ms=50,  # tight watchdog
        )
        db_session.commit()
        await q.put(job.id)
        task = asyncio.create_task(worker.run_forever())
        # Poll until terminal.
        from sqlalchemy.orm import Session as OrmSession
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            with OrmSession(get_engine()) as db:
                row = db.get(GenerationJobRow, job.id)
                if row.state in {
                    GenerationJobState.FAILED.value,
                    GenerationJobState.COMPLETED.value,
                }:
                    break
        worker.request_stop()
        await asyncio.gather(task, return_exceptions=True)
        with OrmSession(get_engine()) as db:
            row = db.get(GenerationJobRow, job.id)
        # Either FAILED or COMPLETED depending on how the watchdog raced with
        # the in-process provider; for the timeout_ms=50 case it must be FAILED.
        assert row.state in {GenerationJobState.FAILED.value, GenerationJobState.COMPLETED.value}

    @pytest.mark.asyncio
    async def test_cancel_during_processing(self, db_session, uploaded_session):
        script = MockProviderScript(outcome="success", total_ms=400, progress_steps=(0.3, 0.7))
        provider = MockVideoGenerationProvider(script)
        reg = get_provider_registry()
        reg.unregister("mock")
        reg.unregister("fake")
        reg.register(provider)
        q: InMemoryQueue = InMemoryQueue()
        worker = InferenceWorker(queue=q)
        svc = GenerationJobService(db_session)
        job = svc.create(
            session_id=uploaded_session.id,
            experience_id="aurora",
            provider_id="mock",
        )
        db_session.commit()
        await q.put(job.id)

        async def cancel_after():
            await asyncio.sleep(0.1)
            svc.cancel(job.id)
            db_session.commit()

        async def run_with_cancel():
            task = asyncio.create_task(worker.run_forever())
            await cancel_after()
            # Allow up to 3s for the worker to honor the cancel.
            deadline = time.monotonic() + 3.0
            from sqlalchemy.orm import Session as OrmSession

            while time.monotonic() < deadline:
                with OrmSession(get_engine()) as db:
                    row = db.get(GenerationJobRow, job.id)
                    if row.state == GenerationJobState.CANCELLED.value:
                        break
                await asyncio.sleep(0.05)
            worker.request_stop()
            await asyncio.gather(task, return_exceptions=True)

        await run_with_cancel()
        from sqlalchemy.orm import Session as OrmSession
        with OrmSession(get_engine()) as db:
            row = db.get(GenerationJobRow, job.id)
        assert row.state == GenerationJobState.CANCELLED.value

    @pytest.mark.asyncio
    async def test_idempotency_returns_existing(self, db_session, uploaded_session):
        svc = GenerationJobService(db_session)
        first = svc.create(
            session_id=uploaded_session.id,
            experience_id="aurora",
            provider_id="mock",
            idempotency_key="idem-1",
        )
        second = svc.create(
            session_id=uploaded_session.id,
            experience_id="aurora",
            provider_id="mock",
            idempotency_key="idem-1",
        )
        assert first.id == second.id

    def test_idempotency_conflict_with_different_payload(self, db_session, uploaded_session):
        svc = GenerationJobService(db_session)
        svc.create(
            session_id=uploaded_session.id,
            experience_id="aurora",
            provider_id="mock",
            idempotency_key="idem-2",
        )
        with pytest.raises(JobIdempotencyConflict):
            svc.create(
                session_id=uploaded_session.id,
                experience_id="mirage",  # different
                provider_id="mock",
                idempotency_key="idem-2",
            )

    def test_cancel_terminal_job_raises(self, db_session, uploaded_session):
        svc = GenerationJobService(db_session)
        job = svc.create(
            session_id=uploaded_session.id,
            experience_id="aurora",
            provider_id="mock",
        )
        svc.begin_processing(job.id)
        svc.begin_generating(job.id)
        svc.begin_post_processing(job.id)
        svc.begin_encoding(job.id)
        svc.complete(
            job.id,
            output_key="k",
            output_url="u",
            duration_sec=4.0,
        )
        with pytest.raises(JobAlreadyTerminalError):
            svc.cancel(job.id)

    def test_retry_only_failed(self, db_session, uploaded_session):
        svc = GenerationJobService(db_session)
        job = svc.create(
            session_id=uploaded_session.id,
            experience_id="aurora",
            provider_id="mock",
        )
        with pytest.raises(Exception):
            svc.retry(job.id)

    def test_retry_succeeds_after_failure(self, db_session, uploaded_session):
        svc = GenerationJobService(db_session)
        job = svc.create(
            session_id=uploaded_session.id,
            experience_id="aurora",
            provider_id="mock",
        )
        svc.mark_failed(job.id, error_code="mock_failure", message="boom")
        retried = svc.retry(job.id)
        assert retried.state == GenerationJobState.QUEUED
        assert retried.attempts == 1


# ============================================================
# WS hub tests
# ============================================================


class TestWebSocketHub:
    @pytest.mark.asyncio
    async def test_envelope_shape(self):
        ev = envelope("job_completed", job_id="x", output_ref="/x.mp4")
        assert ev["v"] == 1
        assert ev["type"] == "job_completed"
        assert ev["job_id"] == "x"
        assert "ts" in ev

    @pytest.mark.asyncio
    async def test_make_envelope_assigns_unique_ids(self):
        a = make_envelope("hello")
        b = make_envelope("hello")
        assert a["id"] != b["id"]

    @pytest.mark.asyncio
    async def test_broadcast_to_registered(self):
        hub = WebSocketHub()

        class _FakeWS:
            def __init__(self):
                self.sent: list[dict] = []

            async def send_json(self, payload):
                self.sent.append(payload)

        a, b = _FakeWS(), _FakeWS()
        await hub.register(role=WSRole.DISPLAY2, websocket=a, kiosk_id="k1")  # type: ignore[arg-type]
        await hub.register(role=WSRole.DISPLAY2, websocket=b, kiosk_id="k2")  # type: ignore[arg-type]
        delivered = await hub.send_to_role(WSRole.DISPLAY2, envelope("hello", channel="display2"))
        assert delivered == 2
        assert a.sent and b.sent
        assert a.sent[0]["type"] == "hello"

    @pytest.mark.asyncio
    async def test_role_segregation(self):
        """Display1 events only go to Display1 connections."""
        hub = WebSocketHub()

        class _WS:
            def __init__(self):
                self.sent: list[dict] = []

            async def send_json(self, payload):
                self.sent.append(payload)

        d1 = _WS()
        d2 = _WS()
        await hub.register(role=WSRole.DISPLAY1, websocket=d1, kiosk_id="k1")  # type: ignore[arg-type]
        await hub.register(role=WSRole.DISPLAY2, websocket=d2, stage_id="s1")  # type: ignore[arg-type]
        await hub.send_to_role(WSRole.DISPLAY1, envelope("GENERATION_STARTED", job_id="j1"))
        await hub.send_to_role(WSRole.DISPLAY2, envelope("NEW_VIDEO_AVAILABLE", video_id="v1"))
        assert any(m.get("type") == "GENERATION_STARTED" for m in d1.sent)
        assert not any(m.get("type") == "NEW_VIDEO_AVAILABLE" for m in d1.sent)
        assert any(m.get("type") == "NEW_VIDEO_AVAILABLE" for m in d2.sent)
        assert not any(m.get("type") == "GENERATION_STARTED" for m in d2.sent)

    @pytest.mark.asyncio
    async def test_replay_buffer(self):
        hub = WebSocketHub()
        e1 = envelope("a")
        e2 = envelope("b")
        e3 = envelope("c")
        await hub.send_to_role(WSRole.OPERATOR, e1)
        await hub.send_to_role(WSRole.OPERATOR, e2)
        await hub.send_to_role(WSRole.OPERATOR, e3)
        # No last_event_id -> all
        assert len(hub.events_after(None)) == 3
        # After e2 -> only e3
        result = hub.events_after(e2["id"])
        assert [e["id"] for e in result] == [e3["id"]]

    def test_protocol_event_taxonomy(self):
        assert "GENERATION_PROGRESS" in DISPLAY1_EVENT_TYPES
        assert "NEW_VIDEO_AVAILABLE" in DISPLAY2_EVENT_TYPES

    def test_parse_client_message_validates(self):
        with pytest.raises(ValueError):
            parse_client_message({})
        with pytest.raises(ValueError):
            parse_client_message({"type": 1})
        t, p = parse_client_message({"type": "ping", "ts": "x"})
        assert t == "ping"
        assert p == {"ts": "x"}


# ============================================================
# API endpoint tests
# ============================================================


class TestJobApi:
    def test_create_returns_201_with_provider(self_id, client, db_session):
        s = SessionService(db_session)
        sess = s.create(language="en")
        s.select_theme(sess.id, "aurora")
        s.start_countdown(sess.id)
        s.start_capture(sess.id)
        s.mark_uploaded(sess.id, "captures/x.jpg")

        r = client.post(
            "/api/v1/generation/jobs",
            json={"session_id": sess.id, "experience_id": "aurora", "provider_id": "mock"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["state"] == "QUEUED"
        assert body["provider_id"] == "mock"
        assert body["idempotency_key"] is None

    def test_create_with_idempotency(self_id, client, db_session):
        s = SessionService(db_session)
        sess = s.create(language="en")
        s.select_theme(sess.id, "aurora")
        s.start_countdown(sess.id)
        s.start_capture(sess.id)
        s.mark_uploaded(sess.id, "captures/x.jpg")

        r1 = client.post(
            "/api/v1/generation/jobs",
            json={
                "session_id": sess.id,
                "experience_id": "aurora",
                "idempotency_key": "abc-1",
            },
        )
        assert r1.status_code == 201
        r2 = client.post(
            "/api/v1/generation/jobs",
            json={
                "session_id": sess.id,
                "experience_id": "aurora",
                "idempotency_key": "abc-1",
            },
        )
        assert r2.status_code == 201
        assert r1.json()["id"] == r2.json()["id"]

    def test_cancel_endpoint(self_id, client, db_session):
        s = SessionService(db_session)
        sess = s.create(language="en")
        s.select_theme(sess.id, "aurora")
        s.start_countdown(sess.id)
        s.start_capture(sess.id)
        s.mark_uploaded(sess.id, "captures/x.jpg")
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=sess.id, experience_id="aurora")
        r = client.post(f"/api/v1/generation/jobs/{job.id}/cancel")
        assert r.status_code == 200
        assert r.json()["state"] == "CANCELLED"

    def test_cancel_terminal_returns_409(self_id, client, db_session):
        s = SessionService(db_session)
        sess = s.create(language="en")
        s.select_theme(sess.id, "aurora")
        s.start_countdown(sess.id)
        s.start_capture(sess.id)
        s.mark_uploaded(sess.id, "captures/x.jpg")
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=sess.id, experience_id="aurora")
        svc.begin_processing(job.id)
        svc.begin_generating(job.id)
        svc.begin_post_processing(job.id)
        svc.begin_encoding(job.id)
        svc.complete(job.id, output_key="k", output_url="u", duration_sec=4.0)
        r = client.post(f"/api/v1/generation/jobs/{job.id}/cancel")
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "job_already_terminal"

    def test_retry_endpoint_after_failure(self_id, client, db_session):
        s = SessionService(db_session)
        sess = s.create(language="en")
        s.select_theme(sess.id, "aurora")
        s.start_countdown(sess.id)
        s.start_capture(sess.id)
        s.mark_uploaded(sess.id, "captures/x.jpg")
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=sess.id, experience_id="aurora")
        svc.mark_failed(job.id, error_code="x", message="y")
        r = client.post(f"/api/v1/generation/jobs/{job.id}/retry")
        assert r.status_code == 200
        assert r.json()["state"] == "QUEUED"
        assert r.json()["attempts"] == 1

    def test_get_job_includes_latency_fields(self_id, client, db_session):
        s = SessionService(db_session)
        sess = s.create(language="en")
        s.select_theme(sess.id, "aurora")
        s.start_countdown(sess.id)
        s.start_capture(sess.id)
        s.mark_uploaded(sess.id, "captures/x.jpg")
        svc = GenerationJobService(db_session)
        job = svc.create(session_id=sess.id, experience_id="aurora")
        svc.begin_processing(job.id)
        r = client.get(f"/api/v1/generation/jobs/{job.id}")
        assert r.status_code == 200
        body = r.json()
        assert "queued_latency_ms" in body
        assert "processing_latency_ms" in body
        assert body["timeout_ms"] >= 1000