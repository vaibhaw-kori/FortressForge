"""End-to-end visitor journeys: API + worker + WS together.

Each test drives kiosk/stage flows concurrently and asserts recovery
without manual restart after every injected failure.
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
from aura_backend.realtime.reel_bus import reel_new_video  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    from aura_backend.middleware.rate_limit import get_limiter

    get_limiter().reset()
    yield
    get_limiter().reset()


# ---------------------------------------------------------------------------
# helpers (local copy so files stay independent)
# ---------------------------------------------------------------------------


def make_jpeg_bytes(size: int = 64) -> bytes:
    try:
        import io

        from PIL import Image

        img = Image.new("RGB", (size, size), color=(90, 200, 120))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        data = buf.getvalue()
        if len(data) < 100:
            data += b"\x00" * (100 - len(data))
        return data
    except Exception:
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
    if r.json()["state"] == "IDLE":
        r = client.post(
            f"/api/v1/sessions/{sid}/transition",
            json={"to": "LANGUAGE_SELECTED", "language": "en"},
        )
        assert r.status_code == 200, r.text
    for body in (
        {"to": "THEME_SELECTED", "theme_id": "aurora"},
        {"to": "COUNTDOWN"},
        {"to": "CAPTURING"},
    ):
        r = client.post(f"/api/v1/sessions/{sid}/transition", json=body)
        assert r.status_code == 200, r.text
    return sid


def _upload(client: TestClient, sid: str, data: bytes, ctype: str = "image/jpeg"):
    return client.post(
        f"/api/v1/sessions/{sid}/capture",
        files={"file": ("c.jpg", data, ctype)},
    )


def _create_job(client: TestClient, sid: str) -> dict[str, Any]:
    r = client.post(
        "/api/v1/generation/jobs",
        json={"session_id": sid, "experience_id": "aurora", "provider_id": "mock"},
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
    pytest.fail("expected hello")


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


def _bump_max(job_id: str, new_max: int = 5):
    from sqlalchemy.orm import Session as OrmSession

    from aura_backend.db import get_engine
    from aura_backend.db.models import GenerationJobRow

    with OrmSession(get_engine()) as db:
        row = db.get(GenerationJobRow, job_id)
        assert row is not None
        row.max_attempts = new_max
        db.commit()


class _FailProvider(MockVideoGenerationProvider):
    provider_id = "mock"

    def __init__(self, exc):
        super().__init__(MockProviderScript(outcome="success", total_ms=10))
        self._exc = exc

    async def submit(self, payload):
        raise self._exc


def _register_fail(exc):
    reg = get_provider_registry()
    reg.unregister("mock")
    reg.unregister("fake")
    p = _FailProvider(exc)
    reg.register(p)
    f = _FailProvider(exc)
    f.provider_id = "fake"  # type: ignore[attr-defined]
    reg.register(f)
    return p


# ---------------------------------------------------------------------------
# e2e tests
# ---------------------------------------------------------------------------


class TestE2EKioskToStage:
    async def test_e2e_happy_path_kiosk_to_stage(self, client, db_session):
        """Kiosk display1 + stage display2 concurrently; COMPLETED fans to both."""
        from aura_backend.storage import get_storage

        _use_mock(MockProviderScript(outcome="success", total_ms=20, progress_steps=(1.0,)))
        sid = _session_to_capturing(client)
        assert _upload(client, sid, make_jpeg_bytes()).status_code == 200
        job = _create_job(client, sid)
        jid = job["id"]

        with client.websocket_connect("/ws/v1/display1/k_e2e1?token=kiosk-dev-token") as d1:
            _hello(d1)
            d1.send_json({"type": "subscribe", "job_id": jid})
            assert _first(d1, "subscribed", timeout=2.0) is not None
            with client.websocket_connect("/ws/v1/display2/st_e2e1?token=kiosk-dev-token") as d2:
                _hello(d2)
                row = await _run_worker_until(jid, timeout=5.0)
                assert row is not None and row.state == "COMPLETED"
                assert get_storage().exists(row.output_key)

                d1_types = [m.get("type") for m in _drain(d1, timeout=1.5)]
                assert "GENERATION_COMPLETED" in d1_types
                d2_types = [m.get("type") for m in _drain(d2, timeout=1.5)]
                assert "NEW_VIDEO_AVAILABLE" in d2_types
                # verify payload correlation via hub buffer
                hub = get_hub()
                found = [
                    e
                    for e in hub._buffer
                    if e.get("type") == "NEW_VIDEO_AVAILABLE" and e.get("job_id") == jid
                ]
                assert found and found[0].get("theme_id") == "aurora"
        # no manual restart needed: session completed
        assert client.get(f"/api/v1/sessions/{sid}").json()["state"] == "COMPLETED"


class TestE2ECameraRecovery:
    async def test_e2e_camera_failure_recovery(self, client, db_session):
        """Camera-unavailable equivalents (invalid/empty) rejected; same session recovers."""
        _use_mock(MockProviderScript(outcome="success", total_ms=15, progress_steps=(1.0,)))
        sid = _session_to_capturing(client)
        # permission-denied / no-person / multi-person surface as invalid captures
        for bad, ctype in [
            (b"", "image/jpeg"),  # camera unavailable / empty frame
            (b"NOTANIMAGE" * 30, "image/jpeg"),  # no person / garbage
            (make_jpeg_bytes(), "text/plain"),  # wrong content-type
        ]:
            r = _upload(client, sid, bad, ctype)
            assert r.status_code == 422, r.text
            assert r.json()["error"]["code"] == "validation_failed"
        # kiosk recovers without new session
        r = _upload(client, sid, make_jpeg_bytes(), "image/jpeg")
        assert r.status_code == 200, r.text
        job = _create_job(client, sid)
        row = await _run_worker_until(job["id"], timeout=5.0)
        assert row is not None and row.state == "COMPLETED"
        assert client.get(f"/api/v1/sessions/{sid}").json()["state"] == "COMPLETED"


class TestE2ERunPodDown:
    async def test_e2e_runpod_down_then_recover(self, client, db_session):
        from aura_backend.errors import ProviderAuthError
        from aura_backend.services import GenerationJobService

        sid = _session_to_capturing(client)
        assert _upload(client, sid, make_jpeg_bytes()).status_code == 200
        job = _create_job(client, sid)
        jid = job["id"]
        _bump_max(jid, 1)
        _register_fail(ProviderAuthError("runpod_auth", "RunPod down"))
        row = await _run_worker_until(jid, timeout=5.0)
        assert row is not None and row.state == "FAILED"

        # next attempt with healthy deps succeeds (no manual restart)
        _use_mock(MockProviderScript(outcome="success", total_ms=15, progress_steps=(1.0,)))
        _bump_max(jid, 5)
        db_session.commit()
        GenerationJobService(db_session).retry(jid)
        db_session.commit()
        row2 = await _run_worker_until(jid, timeout=5.0)
        assert row2 is not None and row2.state == "COMPLETED"


class TestE2EStorageDown:
    async def test_e2e_storage_down_then_recover(self, client, db_session, monkeypatch):
        import aura_backend.api.v1.captures as cap_mod

        _use_mock(MockProviderScript(outcome="success", total_ms=15, progress_steps=(1.0,)))
        sid = _session_to_capturing(client)
        valid = make_jpeg_bytes()

        class _Down:
            def put(self, key, data, content_type="application/octet-stream"):
                raise ConnectionError("minio down")

            def get_url(self, key):
                return f"/x/{key}"

            def exists(self, key):
                return False

            def get(self, key):
                raise FileNotFoundError(key)

        monkeypatch.setattr(cap_mod, "get_storage", lambda: _Down())
        r = _upload(client, sid, valid)
        assert r.status_code == 422
        assert r.json()["error"]["message"] == "Storage failed"

        monkeypatch.undo()
        # recovery without manual restart
        r = _upload(client, sid, valid)
        assert r.status_code == 200, r.text
        job = _create_job(client, sid)
        row = await _run_worker_until(job["id"], timeout=5.0)
        assert row is not None and row.state == "COMPLETED"


class TestE2EWsReconnect:
    async def test_e2e_ws_disconnect_then_reconnect(self, client, db_session):
        _use_mock(MockProviderScript(outcome="success", total_ms=15, progress_steps=(1.0,)))
        sid = _session_to_capturing(client)
        assert _upload(client, sid, make_jpeg_bytes()).status_code == 200
        job = _create_job(client, sid)
        jid = job["id"]

        hub = get_hub()
        with client.websocket_connect("/ws/v1/display1/k_e2e_rc?token=kiosk-dev-token") as ws:
            _hello(ws)
            ws.send_json({"type": "subscribe", "job_id": jid})
            assert _first(ws, "subscribed", timeout=2.0) is not None
            # run worker while connected to get an event id
            row = await _run_worker_until(jid, timeout=5.0)
            assert row is not None and row.state == "COMPLETED"
            comp = _first(ws, "GENERATION_COMPLETED", timeout=2.0)
            assert comp is not None
            last_id = comp["id"]
        # publish another completion-like event while disconnected (simulate missed)
        await event_bus.publish(
            "jobs",
            {"type": "job_completed", "job_id": jid, "session_id": sid, "output_ref": "/v.mp4"},
        )
        await asyncio.sleep(0.1)
        with client.websocket_connect("/ws/v1/display1/k_e2e_rc2?token=kiosk-dev-token") as ws2:
            _hello(ws2)
            ws2.send_json({"type": "hello", "last_event_id": last_id})
            msgs = _drain(ws2, timeout=2.5)
            assert "GENERATION_COMPLETED" in [m.get("type") for m in msgs]


class TestE2EBackendRestart:
    def test_e2e_backend_restart_resumes(self, tmp_path):
        import aura_backend.db as db_module
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session as OrmSession
        from sqlalchemy.orm import sessionmaker

        from aura_backend.db import get_db
        from aura_backend.db.models import Base, GenerationJobRow
        from aura_backend.main import create_app

        orig_e, orig_f = db_module._engine, db_module._SessionLocal
        f = tmp_path / "e2e_restart.db"
        eng = create_engine(f"sqlite:///{f}", connect_args={"check_same_thread": False}, future=True)
        Base.metadata.create_all(bind=eng)
        fac = sessionmaker(bind=eng, autoflush=False, expire_on_commit=False)
        db_module._engine = eng
        db_module._SessionLocal = fac
        try:
            _use_mock(MockProviderScript(outcome="success", total_ms=15, progress_steps=(1.0,)))

            def _ov():
                s = fac()
                try:
                    yield s
                    s.commit()
                except Exception:
                    s.rollback()
                    raise
                finally:
                    s.close()

            a1 = create_app()
            a1.dependency_overrides[get_db] = _ov
            with TestClient(a1) as c1:
                from aura_backend.middleware.rate_limit import get_limiter

                get_limiter().reset()
                r = c1.post("/api/v1/sessions", json={"language": "en"})
                sid = r.json()["id"]
                c1.post(f"/api/v1/sessions/{sid}/transition", json={"to": "THEME_SELECTED", "theme_id": "aurora"})
                c1.post(f"/api/v1/sessions/{sid}/transition", json={"to": "COUNTDOWN"})
                c1.post(f"/api/v1/sessions/{sid}/transition", json={"to": "CAPTURING"})
                assert c1.post(f"/api/v1/sessions/{sid}/capture", files={"file": ("c.jpg", make_jpeg_bytes(), "image/jpeg")}).status_code == 200
                jid = c1.post("/api/v1/generation/jobs", json={"session_id": sid, "experience_id": "aurora", "provider_id": "mock"}).json()["id"]
            with OrmSession(eng) as db:
                assert db.get(GenerationJobRow, jid) is not None

            db_module._engine = eng
            db_module._SessionLocal = fac
            _use_mock(MockProviderScript(outcome="success", total_ms=15, progress_steps=(1.0,)))
            a2 = create_app()
            a2.dependency_overrides[get_db] = _ov
            with TestClient(a2) as c2:
                from aura_backend.middleware.rate_limit import get_limiter

                get_limiter().reset()
                assert c2.get(f"/api/v1/generation/jobs/{jid}").status_code == 200

                async def _resume():
                    from aura_backend.inference.queue import InMemoryQueue
                    from aura_backend.inference.worker import InferenceWorker

                    q: InMemoryQueue = InMemoryQueue()
                    w = InferenceWorker(queue=q)
                    await q.put(jid)
                    t = asyncio.create_task(w.run_forever())
                    try:
                        dl = time.monotonic() + 5.0
                        while time.monotonic() < dl:
                            await asyncio.sleep(0.05)
                            with OrmSession(eng) as db:
                                rr = db.get(GenerationJobRow, jid)
                                if rr is not None and rr.state == "COMPLETED":
                                    return rr
                        with OrmSession(eng) as db:
                            return db.get(GenerationJobRow, jid)
                    finally:
                        w.request_stop()
                        await asyncio.gather(t, return_exceptions=True)

                assert asyncio.run(_resume()).state == "COMPLETED"
        finally:
            eng.dispose()
            db_module._engine = orig_e
            db_module._SessionLocal = orig_f


class TestE2ERepeated5x:
    async def test_e2e_repeated_visitors_5x(self, client, db_session):
        from aura_backend.storage import get_storage

        _use_mock(MockProviderScript(outcome="success", total_ms=15, progress_steps=(1.0,)))
        seen_srcs: set[str] = set()
        for i in range(5):
            sid = _session_to_capturing(client)
            r = _upload(client, sid, make_jpeg_bytes())
            assert r.status_code == 200, f"visitor {i} upload: {r.text}"
            job = _create_job(client, sid)
            row = await _run_worker_until(job["id"], timeout=5.0)
            assert row is not None and row.state == "COMPLETED", f"visitor {i} failed"
            assert get_storage().exists(row.output_key)
            seen_srcs.add(row.output_key)
            # reel playlist grows: hub saw NEW_VIDEO_AVAILABLE for this job
            hub = get_hub()
            assert any(e.get("job_id") == job["id"] for e in hub._buffer), f"reel missing {i}"
        assert len(seen_srcs) == 5
