"""End-to-end tests for the real-time sync layer (WebSocket protocol).

Covers:
- Display1 connect/disconnect
- Display2 connect/disconnect
- operator connect
- handshake (hello, hello_ack, replay)
- job event delivery to subscribers (Display1 + operator)
- reel event delivery (Display2 + operator)
- role separation
- reconnect with last_event_id replay
- invalid client messages return structured error envelopes
- heartbeat (server-initiated pings)
- stale connection cleanup
- control commands operator -> Display2

Uses FastAPI's TestClient for an in-process WebSocket implementation.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aura_backend.events import bus as event_bus
from aura_backend.inference.mock_provider import (
    MockProviderScript,
    MockVideoGenerationProvider,
)
from aura_backend.inference.providers.base import get_provider_registry
from aura_backend.realtime.hub import (
    WebSocketHub,
    envelope,
    get_hub,
    set_hub,
)
from aura_backend.realtime.protocol import (
    DEFAULT_HEARTBEAT_SEC,
    DEFAULT_IDLE_TIMEOUT_SEC,
    WSRole,
    make_envelope,
)
from aura_backend.realtime.reel_bus import (
    reel_new_video,
    reel_play_next,
    reel_play_video,
    reel_refresh_playlist,
    reel_updated,
)
from aura_backend.services import GenerationJobService, SessionService

# Speed up server heartbeats for tests: TestClient receive_json() blocks
# forever, and production heartbeat is 15s, so drains would take 15s each.
# Patch to 0.05s so blocking receives return pings quickly and deadlines work.
import aura_backend.realtime.routes as _ws_routes  # noqa: E402

_WS_TEST_HEARTBEAT = 0.05
_ws_routes.DEFAULT_HEARTBEAT_SEC = _WS_TEST_HEARTBEAT


# ---------------------------------------------------------------------------
# Helpers (single-threaded; relies on fast heartbeat patched below so
# blocking receive_json() returns quickly via ping frames)
# ---------------------------------------------------------------------------


def _hello_envelope(ws) -> dict[str, Any]:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            msg = ws.receive_json()
        except Exception:
            break
        if msg is None:
            break
        if msg.get("type") == "hello":
            assert msg["v"] == 1
            assert msg["role"]
            return msg
    pytest.fail("expected hello envelope")


def _drain(ws, timeout: float = 1.0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = ws.receive_json()
        except Exception:
            break
        if msg is None:
            break
        out.append(msg)
        # fast-heartbeat mode delivers pings frequently; keep draining
        # until deadline so targeted events have time to arrive
    return out


def _first(ws, target_type: str, timeout: float = 5.0) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            msg = ws.receive_json()
        except Exception:
            return None
        if msg is None:
            return None
        if msg.get("type") == target_type:
            return msg
        # ignore pings / other noise, keep waiting
    return None


def _connect_display1(client: TestClient, kiosk_id: str = "k1", token: str = "kiosk-dev-token"):
    return client.websocket_connect(f"/ws/v1/display1/{kiosk_id}?token={token}")


def _connect_display2(client: TestClient, stage_id: str = "stage-1", token: str = "kiosk-dev-token"):
    return client.websocket_connect(f"/ws/v1/display2/{stage_id}?token={token}")


def _connect_operator(client: TestClient, token: str = "kiosk-dev-token"):
    return client.websocket_connect(f"/ws/v1/operator?token={token}")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


class TestConnect:
    def test_display1_connect_sends_hello(self, client):
        with _connect_display1(client) as ws:
            hello = _hello_envelope(ws)
            assert hello["role"] == "display1"
            assert hello["connection_id"]
            # heartbeat tuned fast for tests; accept patched or prod value
            assert hello["heartbeat_sec"] in (DEFAULT_HEARTBEAT_SEC, _WS_TEST_HEARTBEAT)
            assert hello["idle_timeout_sec"] == DEFAULT_IDLE_TIMEOUT_SEC

    def test_display2_connect_sends_hello(self, client):
        with _connect_display2(client) as ws:
            hello = _hello_envelope(ws)
            assert hello["role"] == "display2"

    def test_operator_connect_sends_hello(self, client):
        with _connect_operator(client) as ws:
            hello = _hello_envelope(ws)
            assert hello["role"] == "operator"

    def test_invalid_token_closes_4401(self, client):
        with pytest.raises(Exception):
            with client.websocket_connect("/ws/v1/display1/k1?token=wrong"):
                pass


class TestDisconnect:
    async def test_disconnect_removes_from_registry(self, client):
        hub = get_hub()
        before = hub.connection_count()
        with _connect_display1(client, "k_disconnect") as ws:
            _hello_envelope(ws)
            assert hub.connection_count() == before + 1
        await asyncio.sleep(0.05)
        assert hub.connection_count() == before

    async def test_disconnect_during_event_delivery_does_not_raise(self, client):
        hub = get_hub()
        with _connect_display1(client, "k_killer") as ws:
            _hello_envelope(ws)
        await hub.send_to_role(
            WSRole.DISPLAY1,
            make_envelope("GENERATION_PROGRESS", job_id="x", progress=0.5),
        )


# ---------------------------------------------------------------------------
# Role segregation
# ---------------------------------------------------------------------------


class TestRoleSegregation:
    async def test_display1_does_not_see_reel_events(self, client):
        with _connect_display1(client, "k_role1") as ws:
            _hello_envelope(ws)
            await event_bus.publish(
                "reel",
                reel_new_video(
                    job_id="j1", video_id="v1", src="/v.mp4", duration_sec=4.0, theme_id="aurora"
                ),
            )
            seen = [m for m in _drain(ws) if m.get("type") == "NEW_VIDEO_AVAILABLE"]
            assert seen == []

    async def test_display2_does_not_see_job_events(self, client):
        with _connect_display2(client, "stage_role2") as ws:
            _hello_envelope(ws)
            await event_bus.publish(
                "jobs",
                {"type": "job_progress", "job_id": "j1", "session_id": "s1", "progress": 0.4},
            )
            seen = [m for m in _drain(ws) if m.get("type") == "GENERATION_PROGRESS"]
            assert seen == []

    async def test_operator_receives_both(self, client):
        with _connect_operator(client) as ws:
            _hello_envelope(ws)
            await event_bus.publish(
                "jobs",
                {"type": "job_progress", "job_id": "j1", "session_id": "s1", "progress": 0.4},
            )
            await event_bus.publish(
                "reel",
                reel_new_video(
                    job_id="j1", video_id="v1", src="/v.mp4", duration_sec=4.0, theme_id="aurora"
                ),
            )
            seen = [m.get("type") for m in _drain(ws, timeout=2.0)]
            assert "GENERATION_PROGRESS" in seen
            assert "NEW_VIDEO_AVAILABLE" in seen


# ---------------------------------------------------------------------------
# Event delivery
# ---------------------------------------------------------------------------


class TestEventDelivery:
    async def test_display1_receives_generation_started(self, client):
        with _connect_display1(client, "k_genstart") as ws:
            _hello_envelope(ws)
            # Subscribe to the job channel so we receive events
            ws.send_json({"type": "subscribe", "job_id": "job-1"})
            ack = _first(ws, "subscribed", timeout=2.0)
            assert ack and ack.get("job_id") == "job-1"
            
            await event_bus.publish(
                "jobs",
                {
                    "type": "job_started",
                    "job_id": "job-1",
                    "session_id": "sess-1",
                    "provider_job_id": "rp-1",
                    "attempt": 1,
                },
            )
            msg = _first(ws, "GENERATION_STARTED", timeout=2.0)
            assert msg is not None
            assert msg["job_id"] == "job-1"
            assert msg["role"] == "display1"

    async def test_display1_receives_progress_completed_failed(self, client):
        with _connect_display1(client, "k_lifecycle") as ws:
            _hello_envelope(ws)
            # Subscribe to the job we'll test
            ws.send_json({"type": "subscribe", "job_id": "j"})
            _first(ws, "subscribed", timeout=2.0)
            
            for ev_type, ext in [
                ("job_progress", "GENERATION_PROGRESS"),
                ("job_completed", "GENERATION_COMPLETED"),
                ("job_failed", "GENERATION_FAILED"),
            ]:
                payload: dict[str, Any] = {"type": ev_type, "job_id": "j", "session_id": "s"}
                if ev_type == "job_progress":
                    payload["progress"] = 0.6
                elif ev_type == "job_completed":
                    payload["output_ref"] = "/gen.mp4"
                    payload["duration_sec"] = 4.0
                else:
                    payload["code"] = "fail"
                    payload["message"] = "boom"
                await event_bus.publish("jobs", payload)
            types = [m.get("type") for m in _drain(ws, timeout=2.0)]
            assert "GENERATION_PROGRESS" in types
            assert "GENERATION_COMPLETED" in types
            assert "GENERATION_FAILED" in types

    async def test_display2_receives_new_video_and_play_commands(self, client):
        with _connect_display2(client, "stage_reel") as ws:
            _hello_envelope(ws)
            await event_bus.publish(
                "reel",
                reel_new_video(
                    job_id="j", video_id="v1", src="/v.mp4", duration_sec=4.0, theme_id="aurora"
                ),
            )
            await event_bus.publish("reel", reel_play_next())
            await event_bus.publish("reel", reel_play_video("v1"))
            await event_bus.publish("reel", reel_refresh_playlist())
            await event_bus.publish("reel", reel_updated([], 0))
            types = [m.get("type") for m in _drain(ws, timeout=2.0)]
            assert "NEW_VIDEO_AVAILABLE" in types
            assert "PLAY_NEXT" in types
            assert "PLAY_VIDEO" in types
            assert "REFRESH_PLAYLIST" in types
            assert "REEL_UPDATED" in types

    async def test_job_subscribe_only_delivers_targeted_job(self, client):
        with _connect_display1(client, "k_sub") as ws:
            _hello_envelope(ws)
            ws.send_json({"type": "subscribe", "job_id": "j_target"})
            ack = _first(ws, "subscribed", timeout=2.0)
            assert ack and ack.get("job_id") == "j_target"
            await event_bus.publish(
                "jobs",
                {"type": "job_progress", "job_id": "j_other", "session_id": "s", "progress": 0.5},
            )
            await event_bus.publish(
                "jobs",
                {"type": "job_progress", "job_id": "j_target", "session_id": "s", "progress": 0.5},
            )
            seen = [m for m in _drain(ws, timeout=2.0) if m.get("type") == "GENERATION_PROGRESS"]
            assert len(seen) == 1
            assert seen[0]["job_id"] == "j_target"

    async def test_unsubscribe_stops_delivery(self, client):
        with _connect_display1(client, "k_unsub") as ws:
            _hello_envelope(ws)
            ws.send_json({"type": "subscribe", "job_id": "j1"})
            _first(ws, "subscribed", timeout=2.0)
            ws.send_json({"type": "unsubscribe", "job_id": "j1"})
            _first(ws, "unsubscribed", timeout=2.0)
            await event_bus.publish(
                "jobs",
                {"type": "job_progress", "job_id": "j1", "session_id": "s", "progress": 0.2},
            )
            seen = [m for m in _drain(ws, timeout=1.0) if m.get("type") == "GENERATION_PROGRESS"]
            assert seen == []


# ---------------------------------------------------------------------------
# Reconnect + replay
# ---------------------------------------------------------------------------


class TestReconnect:
    async def test_reconnect_with_last_event_id_replays_missed(self, client):
        """Test that reconnecting with last_event_id replays missed events."""
        from aura_backend.realtime.hub import get_hub

        hub = get_hub()
        # First connection: connect, subscribe, receive some events
        with _connect_display1(client, "k_reconn1") as ws:
            hello = _hello_envelope(ws)
            # Subscribe to job
            ws.send_json({"type": "subscribe", "job_id": "j"})
            _first(ws, "subscribed", timeout=2.0)
            # Receive an event
            await event_bus.publish(
                "jobs",
                {"type": "job_progress", "job_id": "j", "session_id": "s", "progress": 0.3},
            )
            msg1 = _first(ws, "GENERATION_PROGRESS", timeout=2.0)
            assert msg1 is not None
            last_event_id = msg1["id"]
            # Close connection
        # Publish another event while disconnected
        await event_bus.publish(
            "jobs",
            {"type": "job_completed", "job_id": "j", "session_id": "s", "output_ref": "/v.mp4"},
        )
        # Verify the event is in the hub buffer
        await asyncio.sleep(0.1)
        buffer_ids = [ev.get("id") for ev in hub._buffer]
        assert last_event_id in buffer_ids, f"last_event_id {last_event_id} not in buffer {buffer_ids}"
        # Reconnect with last_event_id -> server should replay missed events
        with _connect_display1(client, "k_reconn2") as ws:
            # Drain initial hello
            _hello_envelope(ws)
            # Send hello with last_event_id
            ws.send_json({"type": "hello", "last_event_id": last_event_id})
            # Drain ALL messages and look for replayed events
            all_msgs = _drain(ws, timeout=3.0)
            # The replayed events should be in all_msgs
            replayed_types = [m.get("type") for m in all_msgs if m.get("type") in (
                "GENERATION_STARTED", "GENERATION_PROGRESS", "GENERATION_COMPLETED", "GENERATION_FAILED"
            )]
            assert "GENERATION_COMPLETED" in replayed_types, (
                f"expected GENERATION_COMPLETED in replayed events, got {replayed_types}"
            )


# ---------------------------------------------------------------------------
# Invalid client messages
# ---------------------------------------------------------------------------


class TestInvalidClientMessages:
    def test_non_json_message(self, client):
        with _connect_display1(client, "k_bad1") as ws:
            _hello_envelope(ws)
            ws.send_text("not-json-at-all")
            err = _first(ws, "error", timeout=2.0)
            assert err is not None
            assert err.get("reason") == "invalid_json"

    def test_json_missing_type(self, client):
        with _connect_display1(client, "k_bad2") as ws:
            _hello_envelope(ws)
            ws.send_text(json.dumps({"foo": "bar"}))
            err = _first(ws, "error", timeout=2.0)
            assert err is not None

    def test_subscribe_without_job_id(self, client):
        with _connect_display1(client, "k_bad3") as ws:
            _hello_envelope(ws)
            ws.send_json({"type": "subscribe"})
            err = _first(ws, "error", timeout=2.0)
            assert err is not None
            assert "missing_job_id" in err.get("reason", "")

    def test_unknown_type(self, client):
        with _connect_display1(client, "k_bad4") as ws:
            _hello_envelope(ws)
            ws.send_json({"type": "make_coffee"})
            err = _first(ws, "error", timeout=2.0)
            assert err is not None
            assert "unknown_type" in err.get("reason", "")


# ---------------------------------------------------------------------------
# Control commands
# ---------------------------------------------------------------------------


class TestControlCommands:
    async def test_operator_play_next_reaches_display2(self, client):
        with _connect_operator(client) as op_ws:
            _hello_envelope(op_ws)
            with _connect_display2(client, "stage_ctrl") as d2_ws:
                _hello_envelope(d2_ws)
                op_ws.send_json({"type": "play_next"})
                _first(op_ws, "control_ack", timeout=2.0)
                seen = [m.get("type") for m in _drain(d2_ws, timeout=2.0)]
                assert "PLAY_NEXT" in seen

    async def test_operator_play_video_includes_video_id(self, client):
        with _connect_operator(client) as op_ws:
            _hello_envelope(op_ws)
            with _connect_display2(client, "stage_ctrl2") as d2_ws:
                _hello_envelope(d2_ws)
                op_ws.send_json({"type": "play_video", "video_id": "vid-xyz"})
                _first(op_ws, "control_ack", timeout=2.0)
                msgs = [m for m in _drain(d2_ws, timeout=2.0) if m.get("type") == "PLAY_VIDEO"]
                assert msgs and msgs[0]["video_id"] == "vid-xyz"


# ---------------------------------------------------------------------------
# Stale cleanup (unit)
# ---------------------------------------------------------------------------


class TestStaleCleanup:
    async def test_stale_connection_is_evicted_after_idle_timeout(self):
        from starlette.websockets import WebSocket

        hub = WebSocketHub(heartbeat_sec=0.05, idle_timeout_sec=0.1)
        sent: list = []

        class _WS:
            async def send_json(self, payload):
                sent.append(payload)

            async def close(self, code=1001, reason=""):
                pass

        ws = _WS()
        await hub.register(role=WSRole.DISPLAY1, websocket=ws, kiosk_id="k")  # type: ignore[arg-type]
        await hub.start()
        await asyncio.sleep(0.4)
        assert hub.connection_count() == 0
        await hub.stop()


# ---------------------------------------------------------------------------
# End-to-end: real worker drives Display1 + Display2 events
# ---------------------------------------------------------------------------


class TestEndToEndWithWorker:
    async def test_completed_job_drives_both_displays(self, client, db_session):
        from sqlalchemy.orm import Session as OrmSession

        from aura_backend.db import get_engine
        from aura_backend.db.models import GenerationJobRow
        from aura_backend.inference.queue import InMemoryQueue
        from aura_backend.inference.worker import InferenceWorker

        prov = MockVideoGenerationProvider(
            MockProviderScript(outcome="success", total_ms=10, progress_steps=(1.0,))
        )
        reg = get_provider_registry()
        reg.unregister("mock")
        reg.unregister("fake")
        reg.register(prov)

        ss = SessionService(db_session)
        sess = ss.create(language="en")
        ss.select_theme(sess.id, "aurora")
        ss.start_countdown(sess.id)
        ss.start_capture(sess.id)
        ss.mark_uploaded(sess.id, "cap.jpg")
        gs = GenerationJobService(db_session)
        job = gs.create(session_id=sess.id, experience_id="aurora", provider_id="mock")
        db_session.commit()

        with _connect_display1(client, "k_e2e_d1") as d1_ws:
            _hello_envelope(d1_ws)
            # Subscribe to the job
            d1_ws.send_json({"type": "subscribe", "job_id": job.id})
            _first(d1_ws, "subscribed", timeout=2.0)
            with _connect_display2(client, "stage_e2e") as d2_ws:
                _hello_envelope(d2_ws)

                queue: InMemoryQueue = InMemoryQueue()
                worker = InferenceWorker(queue=queue)
                await queue.put(job.id)
                task = asyncio.create_task(worker.run_forever())

                end = time.monotonic() + 3.0
                while time.monotonic() < end:
                    with OrmSession(get_engine()) as db:
                        row = db.get(GenerationJobRow, job.id)
                        if row is not None and row.state == "COMPLETED":
                            break
                    await asyncio.sleep(0.05)
                worker.request_stop()
                await asyncio.gather(task, return_exceptions=True)

                d1_msgs = [m for m in _drain(d1_ws, timeout=2.0)]
                d1_types = [m.get("type") for m in d1_msgs]
                assert "GENERATION_COMPLETED" in d1_types

                d2_msgs = [m for m in _drain(d2_ws, timeout=2.0)]
                d2_types = [m.get("type") for m in d2_msgs]
                assert "NEW_VIDEO_AVAILABLE" in d2_types
                new_vid = next(m for m in d2_msgs if m.get("type") == "NEW_VIDEO_AVAILABLE")
                assert new_vid["job_id"] == job.id
                assert new_vid["theme_id"] == "aurora"
                assert isinstance(new_vid["src"], str)

    async def test_failed_job_drives_display1_failure_event(self, client, db_session):
        from sqlalchemy.orm import Session as OrmSession

        from aura_backend.db import get_engine
        from aura_backend.db.models import GenerationJobRow
        from aura_backend.inference.queue import InMemoryQueue
        from aura_backend.inference.worker import InferenceWorker

        prov = MockVideoGenerationProvider(
            MockProviderScript(outcome="fail", total_ms=10, fail_after_ms=0)
        )
        reg = get_provider_registry()
        reg.unregister("mock")
        reg.unregister("fake")
        reg.register(prov)
        ss = SessionService(db_session)
        sess = ss.create(language="en")
        ss.select_theme(sess.id, "aurora")
        ss.start_countdown(sess.id)
        ss.start_capture(sess.id)
        ss.mark_uploaded(sess.id, "cap.jpg")
        gs = GenerationJobService(db_session)
        job = gs.create(session_id=sess.id, experience_id="aurora", provider_id="mock")
        db_session.commit()

        with _connect_display1(client, "k_fail_d1") as d1_ws:
            _hello_envelope(d1_ws)
            # Subscribe to the job
            d1_ws.send_json({"type": "subscribe", "job_id": job.id})
            _first(d1_ws, "subscribed", timeout=2.0)
            queue: InMemoryQueue = InMemoryQueue()
            worker = InferenceWorker(queue=queue)
            await queue.put(job.id)
            task = asyncio.create_task(worker.run_forever())
            end = time.monotonic() + 3.0
            while time.monotonic() < end:
                with OrmSession(get_engine()) as db:
                    row = db.get(GenerationJobRow, job.id)
                    if row is not None and row.state == "FAILED":
                        break
                await asyncio.sleep(0.05)
            worker.request_stop()
            await asyncio.gather(task, return_exceptions=True)
            d1_types = [m.get("type") for m in _drain(d1_ws, timeout=2.0)]
            assert "GENERATION_FAILED" in d1_types