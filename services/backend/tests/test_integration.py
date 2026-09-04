"""Backend integration: DB + services + API + storage + realtime relay.

Covers visitor happy path, capture/storage failures + recovery,
RunPod/provider failures + retry, corrupt output, WS reconnect,
backend restart, repeated sessions, display2 playback failure.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import aura_backend.realtime.routes as _r

_r.DEFAULT_HEARTBEAT_SEC = 0.05

from aura_backend.events import bus as event_bus  # noqa: E402
from aura_backend.inference.mock_provider import (  # noqa: E402
    MockProviderScript,
    MockVideoGenerationProvider,
)
from aura_backend.inference.providers.base import get_provider_registry  # noqa: E402
from aura_backend.realtime.hub import get_hub  # noqa: E402
from aura_backend.realtime.reel_bus import (  # noqa: E402
    reel_new_video,
    reel_play_next,
    reel_updated,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    from aura_backend.middleware.rate_limit import get_limiter

    get_limiter().reset()
    yield
    get_limiter().reset()


def make_jpeg_bytes(size: int = 64) -> bytes:
    """Minimal valid JPEG (PIL if available, else crafted magic + padding)."""
    try:
        import io

        from PIL import Image

        img = Image.new("RGB", (size, size), color=(124, 92, 255))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        data = buf.getvalue()
        if len(data) < 100:
            data += b"\x00" * (100 - len(data))
        return data
    except Exception:
        # Fallback: JPEG magic + padding. Passes magic + size checks and,
        # when Pillow is absent, the content fallback in captures.py.
        return b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 2000


def _use_mock(script: MockProviderScript | None = None):
    script = script or MockProviderScript(outcome="success", total_ms=20, progress_steps=(1.0,))
    prov = MockVideoGenerationProvider(script)
    reg = get_provider_registry()
    reg.unregister("mock")
    reg.unregister("fake")
    reg.register(prov)
    fake = MockVideoGenerationProvider(script)
    fake.provider_id = "fake"  # type: ignore[attr-defined]
    reg.register(fake)
    return prov


def _session_to_capturing(client: TestClient) -> str:
    r = client.post("/api/v1/sessions", json={"language": "en"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    state = r.json()["state"]
    if state == "IDLE":
        r = client.post(
            f"/api/v1/sessions/{sid}/transition",
            json={"to": "LANGUAGE_SELECTED", "language": "en"},
        )
        assert r.status_code == 200, r.text
    r = client.post(
        f"/api/v1/sessions/{sid}/transition",
        json={"to": "THEME_SELECTED", "theme_id": "aurora"},
    )
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/sessions/{sid}/transition", json={"to": "COUNTDOWN"})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/v1/sessions/{sid}/transition", json={"to": "CAPTURING"})
    assert r.status_code == 200, r.text
    return sid


def _upload(client: TestClient, sid: str, data: bytes, ctype: str = "image/jpeg"):
    return client.post(
        f"/api/v1/sessions/{sid}/capture",
        files={"file": ("c.jpg", data, ctype)},
    )


def _create_job(client: TestClient, sid: str, provider: str = "mock") -> dict[str, Any]:
    r = client.post(
        "/api/v1/generation/jobs",
        json={"session_id": sid, "experience_id": "aurora", "provider_id": provider},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _run_worker_until(job_id: str, terminal=("COMPLETED", "FAILED"), timeout: float = 5.0):
    from sqlalchemy.orm import Session as OrmSession

    from aura_backend.db import get_engine
    from aura_backend.db.models import GenerationJobRow
    from aura_backend.inference.queue import InMemoryQueue
    from aura_backend.inference.worker import InferenceWorker

    q: InMemoryQueue = InMemoryQueue()
    w = InferenceWorker(queue=q)
    await q.put(job_id)
    task = asyncio.create_task(w.run_forever())
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(0.05)
            with OrmSession(get_engine()) as db:
                row = db.get(GenerationJobRow, job_id)
                if row is not None and row.state in terminal:
                    return row
        with OrmSession(get_engine()) as db:
            return db.get(GenerationJobRow, job_id)
    finally:
        w.request_stop()
        await asyncio.gather(task, return_exceptions=True)


def _row(job_id: str):
    from sqlalchemy.orm import Session as OrmSession

    from aura_backend.db import get_engine
    from aura_backend.db.models import GenerationJobRow

    with OrmSession(get_engine()) as db:
        row = db.get(GenerationJobRow, job_id)
        assert row is not None
        # detach values
        return row


def _hello(ws):
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            msg = ws.receive_json()
        except Exception:
            break
        if msg is None:
            break
        if msg.get("type") == "hello":
            return msg
    pytest.fail("expected hello envelope")


def _drain(ws, timeout: float = 1.2):
    out = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = ws.receive_json()
        except Exception:
            break
        if msg is None:
            break
        out.append(msg)
    return out


def _first(ws, target: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = ws.receive_json()
        except Exception:
            return None
        if msg is None:
            return None
        if msg.get("type") == target:
            return msg
    return None


def _bump_max_attempts(job_id: str, new_max: int = 5):
    """Allow one more retry after worker exhausted attempts (test helper)."""
    from sqlalchemy.orm import Session as OrmSession

    from aura_backend.db import get_engine
    from aura_backend.db.models import GenerationJobRow

    with OrmSession(get_engine()) as db:
        row = db.get(GenerationJobRow, job_id)
        assert row is not None
        row.max_attempts = new_max
        db.commit()


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------


class TestVisitorHappyPath:
    async def test_full_visitor_happy_path(self, client, db_session):
        from aura_backend.storage import get_storage

        _use_mock(MockProviderScript(outcome="success", total_ms=20, progress_steps=(1.0,)))
        sid = _session_to_capturing(client)
        data = make_jpeg_bytes()
        assert len(data) >= 100
        r = _upload(client, sid, data, "image/jpeg")
        assert r.status_code == 200, r.text
        key = r.json()["key"]
        assert get_storage().exists(key)

        rs = client.get(f"/api/v1/sessions/{sid}")
        assert rs.status_code == 200
        assert rs.json()["state"] == "UPLOADED"

        job = _create_job(client, sid)
        jid = job["id"]
        assert job["state"] == "QUEUED"

        # Subscribe display1 to job + hold display2 open for reel fan-out.
        with client.websocket_connect("/ws/v1/display1/k_happy?token=kiosk-dev-token") as d1:
            _hello(d1)
            d1.send_json({"type": "subscribe", "job_id": jid})
            assert _first(d1, "subscribed", timeout=2.0) is not None
            with client.websocket_connect("/ws/v1/display2/stage_happy?token=kiosk-dev-token") as d2:
                _hello(d2)
                row = await _run_worker_until(jid, timeout=5.0)
                assert row is not None and row.state == "COMPLETED"
                assert row.output_key is not None
                assert get_storage().exists(row.output_key)

                d1_types = [m.get("type") for m in _drain(d1, timeout=1.5)]
                assert "GENERATION_COMPLETED" in d1_types
                d2_types = [m.get("type") for m in _drain(d2, timeout=1.5)]
                assert "NEW_VIDEO_AVAILABLE" in d2_types
                # hub buffer also fanned
                hub = get_hub()
                buf = [e for e in hub._buffer if e.get("type") == "NEW_VIDEO_AVAILABLE" and e.get("job_id") == jid]
                assert buf, "reel event not fanned to hub"

        # session driven to COMPLETED by worker
        rs = client.get(f"/api/v1/sessions/{sid}")
        assert rs.json()["state"] == "COMPLETED"
        # job filtered by session
        rj = client.get(f"/api/v1/generation/jobs?session_id={sid}")
        assert rj.status_code == 200
        assert any(j["id"] == jid for j in rj.json())


# ---------------------------------------------------------------------------
# capture failures
# ---------------------------------------------------------------------------


class TestCaptureFailures:
    def test_capture_failures_stay_capturing_then_recover(self, client, db_session):
        from aura_backend.api.v1 import captures as cap_mod

        sid = _session_to_capturing(client)
        valid = make_jpeg_bytes()

        # bad magic
        r = _upload(client, sid, b"NOTANIMAGE" * 30, "image/jpeg")
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_failed"
        # empty
        r = _upload(client, sid, b"", "image/jpeg")
        assert r.status_code == 422
        # too large
        big = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * (cap_mod.MAX_CAPTURE_BYTES + 1)
        r = _upload(client, sid, big, "image/jpeg")
        assert r.status_code == 422
        # wrong content-type
        r = _upload(client, sid, valid, "text/plain")
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_failed"

        # session stays CAPTURING (recoverable)
        rs = client.get(f"/api/v1/sessions/{sid}")
        assert rs.json()["state"] == "CAPTURING"

        # retry with valid succeeds without new session
        r = _upload(client, sid, valid, "image/jpeg")
        assert r.status_code == 200, r.text
        rs = client.get(f"/api/v1/sessions/{sid}")
        assert rs.json()["state"] == "UPLOADED"

    def test_upload_failure_then_retry_succeeds(self, client, db_session):
        sid = _session_to_capturing(client)
        # simulate camera producing garbage first
        r = _upload(client, sid, b"BADBYTES" * 40, "image/jpeg")
        assert r.status_code == 422
        # recovery without manual restart: same session, valid retry
        r = _upload(client, sid, make_jpeg_bytes(), "image/jpeg")
        assert r.status_code == 200
        job = _create_job(client, sid)
        assert job["state"] == "QUEUED"


# ---------------------------------------------------------------------------
# storage unavailable
# ---------------------------------------------------------------------------


class TestStorageFailure:
    def test_storage_unavailable_422_then_recover(self, client, db_session, monkeypatch):
        import aura_backend.api.v1.captures as cap_mod

        sid = _session_to_capturing(client)
        valid = make_jpeg_bytes()

        class _Exploding:
            def put(self, key, data, content_type="application/octet-stream"):
                raise RuntimeError("SECRET disk s3://internal exploded")

            def get_url(self, key):
                return f"/x/{key}"

            def exists(self, key):
                return False

            def get(self, key):
                raise FileNotFoundError(key)

        monkeypatch.setattr(cap_mod, "get_storage", lambda: _Exploding())
        r = _upload(client, sid, valid, "image/jpeg")
        assert r.status_code == 422, r.text
        body = r.json()
        assert body["error"]["code"] == "validation_failed"
        assert body["error"]["message"] == "Storage failed"
        assert "SECRET" not in body["error"]["message"]

        # restore happens via monkeypatch undo; retry succeeds (no manual restart)
        monkeypatch.undo()
        r = _upload(client, sid, valid, "image/jpeg")
        assert r.status_code == 200, r.text
        from aura_backend.storage import get_storage

        assert get_storage().exists(r.json()["key"])


# ---------------------------------------------------------------------------
# provider failures (RunPod equivalents) + retry
# ---------------------------------------------------------------------------


class _FailProvider(MockVideoGenerationProvider):
    provider_id = "mock"

    def __init__(self, exc):
        super().__init__(MockProviderScript(outcome="success", total_ms=10))
        self._exc = exc

    async def submit(self, payload):
        raise self._exc


def _register_fail_provider(exc):
    from aura_backend.inference.providers.base import get_provider_registry

    reg = get_provider_registry()
    reg.unregister("mock")
    reg.unregister("fake")
    p = _FailProvider(exc)
    reg.register(p)
    fake = _FailProvider(exc)
    fake.provider_id = "fake"  # type: ignore[attr-defined]
    reg.register(fake)
    return p


class TestProviderFailures:
    async def test_runpod_auth_failure_then_retry_succeeds(self, client, db_session):
        from aura_backend.errors import ProviderAuthError
        from aura_backend.services import GenerationJobService

        sid = _session_to_capturing(client)
        assert _upload(client, sid, make_jpeg_bytes()).status_code == 200
        job = _create_job(client, sid)
        jid = job["id"]
        # bump max so worker has room; failing provider still exhausts quickly
        _bump_max_attempts(jid, 1)

        _register_fail_provider(ProviderAuthError("runpod_auth", "no api key"))
        row = await _run_worker_until(jid, timeout=5.0)
        assert row is not None and row.state == "FAILED"
        assert row.error_code is not None
        assert "auth" in row.error_code.lower() or "runpod" in row.error_code.lower()

        # recovery: healthy mock + retry succeeds without manual restart
        _use_mock(MockProviderScript(outcome="success", total_ms=20, progress_steps=(1.0,)))
        _bump_max_attempts(jid, 5)
        svc = GenerationJobService(db_session)
        # re-load job in this session
        db_session.commit()
        retried = svc.retry(jid)
        db_session.commit()
        assert retried.state.value == "QUEUED"
        row2 = await _run_worker_until(jid, timeout=5.0)
        assert row2 is not None and row2.state == "COMPLETED"

    async def test_runpod_timeout_then_retry_succeeds(self, client, db_session):
        from aura_backend.errors import ProviderTimeoutError
        from aura_backend.services import GenerationJobService

        sid = _session_to_capturing(client)
        assert _upload(client, sid, make_jpeg_bytes()).status_code == 200
        job = _create_job(client, sid)
        jid = job["id"]
        _bump_max_attempts(jid, 1)

        _register_fail_provider(ProviderTimeoutError("runpod_poll_timeout", "timed out"))
        row = await _run_worker_until(jid, timeout=5.0)
        assert row is not None and row.state == "FAILED"
        assert row.error_code is not None
        assert "timeout" in row.error_code.lower()

        _use_mock(MockProviderScript(outcome="success", total_ms=20, progress_steps=(1.0,)))
        _bump_max_attempts(jid, 5)
        svc = GenerationJobService(db_session)
        db_session.commit()
        retried = svc.retry(jid)
        db_session.commit()
        assert retried.state.value == "QUEUED"
        row2 = await _run_worker_until(jid, timeout=5.0)
        assert row2 is not None and row2.state == "COMPLETED"

    async def test_generation_failure_then_retry(self, client, db_session):
        from aura_backend.services import GenerationJobService

        _use_mock(MockProviderScript(outcome="fail", total_ms=10, fail_after_ms=0))
        sid = _session_to_capturing(client)
        assert _upload(client, sid, make_jpeg_bytes()).status_code == 200
        job = _create_job(client, sid)
        jid = job["id"]
        _bump_max_attempts(jid, 1)
        row = await _run_worker_until(jid, timeout=5.0)
        assert row is not None and row.state == "FAILED"

        # retry with success script → COMPLETED (no manual restart)
        _use_mock(MockProviderScript(outcome="success", total_ms=20, progress_steps=(1.0,)))
        _bump_max_attempts(jid, 5)
        svc = GenerationJobService(db_session)
        db_session.commit()
        svc.retry(jid)
        db_session.commit()
        row2 = await _run_worker_until(jid, timeout=5.0)
        assert row2 is not None and row2.state == "COMPLETED"

    async def test_corrupt_output_graceful(self, client, db_session):
        for bad_ref in ("", "corrupt!!!"):
            _use_mock(
                MockProviderScript(
                    outcome="success", total_ms=10, progress_steps=(1.0,), output_ref=bad_ref
                )
            )
            sid = _session_to_capturing(client)
            assert _upload(client, sid, make_jpeg_bytes()).status_code == 200
            job = _create_job(client, sid)
            jid = job["id"]
            row = await _run_worker_until(jid, timeout=5.0)
            # must reach terminal state without crashing worker
            assert row is not None and row.state in ("COMPLETED", "FAILED"), bad_ref
            if row.state == "COMPLETED":
                assert row.output_key is not None


# ---------------------------------------------------------------------------
# WS reconnect
# ---------------------------------------------------------------------------


class TestWsReconnect:
    async def test_disconnect_reconnect_replays_completed(self, client):
        hub = get_hub()
        # first connection: subscribe
        with client.websocket_connect("/ws/v1/display1/k_rc1?token=kiosk-dev-token") as ws:
            _hello(ws)
            ws.send_json({"type": "subscribe", "job_id": "j-reconnect"})
            assert _first(ws, "subscribed", timeout=2.0) is not None
            await event_bus.publish(
                "jobs",
                {"type": "job_progress", "job_id": "j-reconnect", "session_id": "s", "progress": 0.3},
            )
            m1 = _first(ws, "GENERATION_PROGRESS", timeout=2.0)
            assert m1 is not None
            last_id = m1["id"]
        # publish while disconnected
        await event_bus.publish(
            "jobs",
            {"type": "job_completed", "job_id": "j-reconnect", "session_id": "s", "output_ref": "/v.mp4"},
        )
        await asyncio.sleep(0.1)
        assert last_id in [e.get("id") for e in hub._buffer]
        # reconnect with last_event_id → replay missed COMPLETED
        with client.websocket_connect("/ws/v1/display1/k_rc2?token=kiosk-dev-token") as ws2:
            _hello(ws2)
            ws2.send_json({"type": "hello", "last_event_id": last_id})
            msgs = _drain(ws2, timeout=2.5)
            types = [m.get("type") for m in msgs]
            assert "GENERATION_COMPLETED" in types


# ---------------------------------------------------------------------------
# backend restart
# ---------------------------------------------------------------------------


class TestBackendRestart:
    def test_file_db_restart_resumes_job(self, tmp_path):
        import aura_backend.db as db_module
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker, Session as OrmSession

        from aura_backend.db import get_db
        from aura_backend.db.models import Base, GenerationJobRow
        from aura_backend.main import create_app

        orig_engine = db_module._engine
        orig_factory = db_module._SessionLocal
        db_file = tmp_path / "restart.db"
        file_engine = create_engine(
            f"sqlite:///{db_file}", connect_args={"check_same_thread": False}, future=True
        )
        Base.metadata.create_all(bind=file_engine)
        file_factory = sessionmaker(bind=file_engine, autoflush=False, expire_on_commit=False)
        db_module._engine = file_engine
        db_module._SessionLocal = file_factory
        try:
            _use_mock(MockProviderScript(outcome="success", total_ms=20, progress_steps=(1.0,)))

            def _override():
                s = file_factory()
                try:
                    yield s
                    s.commit()
                except Exception:
                    s.rollback()
                    raise
                finally:
                    s.close()

            app1 = create_app()
            app1.dependency_overrides[get_db] = _override
            with TestClient(app1) as c1:
                from aura_backend.middleware.rate_limit import get_limiter

                get_limiter().reset()
                # drive via API on file DB
                r = c1.post("/api/v1/sessions", json={"language": "en"})
                assert r.status_code == 201
                sid = r.json()["id"]
                c1.post(
                    f"/api/v1/sessions/{sid}/transition",
                    json={"to": "THEME_SELECTED", "theme_id": "aurora"},
                )
                c1.post(f"/api/v1/sessions/{sid}/transition", json={"to": "COUNTDOWN"})
                c1.post(f"/api/v1/sessions/{sid}/transition", json={"to": "CAPTURING"})
                up = c1.post(
                    f"/api/v1/sessions/{sid}/capture",
                    files={"file": ("c.jpg", make_jpeg_bytes(), "image/jpeg")},
                )
                assert up.status_code == 200, up.text
                jr = c1.post(
                    "/api/v1/generation/jobs",
                    json={"session_id": sid, "experience_id": "aurora", "provider_id": "mock"},
                )
                assert jr.status_code == 201
                jid = jr.json()["id"]
                # dispose client = lifespan stop (backend restart simulation)
            # job row still present after "restart"
            with OrmSession(file_engine) as db:
                row = db.get(GenerationJobRow, jid)
                assert row is not None
                assert row.state == "QUEUED"

            # NEW app+client with SAME file DB
            _use_mock(MockProviderScript(outcome="success", total_ms=20, progress_steps=(1.0,)))
            db_module._engine = file_engine
            db_module._SessionLocal = file_factory
            app2 = create_app()
            app2.dependency_overrides[get_db] = _override
            with TestClient(app2) as c2:
                from aura_backend.middleware.rate_limit import get_limiter

                get_limiter().reset()
                r = c2.get(f"/api/v1/generation/jobs/{jid}")
                assert r.status_code == 200
                assert r.json()["id"] == jid

                # worker resumes job to COMPLETED using file engine
                async def _resume():
                    from aura_backend.inference.queue import InMemoryQueue
                    from aura_backend.inference.worker import InferenceWorker

                    q: InMemoryQueue = InMemoryQueue()
                    w = InferenceWorker(queue=q)
                    await q.put(jid)
                    task = asyncio.create_task(w.run_forever())
                    try:
                        deadline = time.monotonic() + 5.0
                        while time.monotonic() < deadline:
                            await asyncio.sleep(0.05)
                            with OrmSession(file_engine) as db:
                                rr = db.get(GenerationJobRow, jid)
                                if rr is not None and rr.state == "COMPLETED":
                                    return rr
                        with OrmSession(file_engine) as db:
                            return db.get(GenerationJobRow, jid)
                    finally:
                        w.request_stop()
                        await asyncio.gather(task, return_exceptions=True)

                row2 = asyncio.run(_resume())
                assert row2 is not None and row2.state == "COMPLETED"
        finally:
            file_engine.dispose()
            db_module._engine = orig_engine
            db_module._SessionLocal = orig_factory

    async def test_hub_restart_isolation(self, client, db_session):
        from aura_backend.realtime.hub import reset_hub
        from aura_backend.realtime.relay import install_relay, uninstall_relay

        hub = get_hub()
        # hub.stop clears connections; new hub starts clean, relay reinstalls
        await hub.stop()
        assert hub.connection_count() == 0
        reset_hub()
        uninstall_relay()
        install_relay()
        new_hub = get_hub()
        assert new_hub.connection_count() == 0
        # queued job can still be re-driven after relay reinstall
        _use_mock(MockProviderScript(outcome="success", total_ms=10, progress_steps=(1.0,)))
        from aura_backend.services import GenerationJobService, SessionService

        ss = SessionService(db_session)
        s = ss.create(language="en")
        ss.select_theme(s.id, "aurora")
        ss.start_countdown(s.id)
        ss.start_capture(s.id)
        ss.mark_uploaded(s.id, "captures/x.jpg")
        db_session.commit()
        gs = GenerationJobService(db_session)
        job = gs.create(session_id=s.id, experience_id="aurora", provider_id="mock")
        db_session.commit()
        row = await _run_worker_until(job.id, timeout=5.0)
        assert row is not None and row.state == "COMPLETED"


# ---------------------------------------------------------------------------
# repeated sessions
# ---------------------------------------------------------------------------


class TestRepeatedSessions:
    async def test_three_back_to_back_no_contamination(self, client, db_session):
        _use_mock(MockProviderScript(outcome="success", total_ms=15, progress_steps=(1.0,)))
        from aura_backend.storage import get_storage

        sids: list[str] = []
        jids: list[str] = []
        for _ in range(3):
            sid = _session_to_capturing(client)
            assert _upload(client, sid, make_jpeg_bytes()).status_code == 200
            job = _create_job(client, sid)
            jid = job["id"]
            sids.append(sid)
            jids.append(jid)
            row = await _run_worker_until(jid, timeout=5.0)
            assert row is not None and row.state == "COMPLETED"
            assert get_storage().exists(row.output_key)
        assert len(set(sids)) == 3 and len(set(jids)) == 3
        for sid, jid in zip(sids, jids):
            r = client.get(f"/api/v1/generation/jobs?session_id={sid}")
            assert r.status_code == 200
            ids = [j["id"] for j in r.json()]
            assert ids == [jid], f"cross-contamination for {sid}: {ids}"


# ---------------------------------------------------------------------------
# display2 playback failure
# ---------------------------------------------------------------------------


class TestDisplay2Playback:
    async def test_faulty_video_removal_advances(self, client):
        with client.websocket_connect("/ws/v1/display2/stage_pb?token=kiosk-dev-token") as d2:
            _hello(d2)
            await event_bus.publish(
                "reel",
                reel_new_video(
                    job_id="j-pb", video_id="v-pb", src="/gen.mp4", duration_sec=4.0, theme_id="aurora"
                ),
            )
            # simulate faulty video removal: broadcast updated + play_next
            await event_bus.publish("reel", reel_updated([{"id": "v-good", "src": "/gen/good.mp4"}], 1))
            await event_bus.publish("reel", reel_play_next())
            msgs = _drain(d2, timeout=2.0)
            by_type = {m.get("type"): m for m in msgs}
            assert "NEW_VIDEO_AVAILABLE" in by_type
            assert "REEL_UPDATED" in by_type
            assert "PLAY_NEXT" in by_type
            assert by_type["REEL_UPDATED"]["queue_length"] == 1
