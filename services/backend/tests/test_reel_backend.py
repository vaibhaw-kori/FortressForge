"""Reel backend tests: domain, repository, reel_bus helpers, relay fan-out, display2 delivery."""

from __future__ import annotations

import time

import pytest

from aura_backend.domain import ReelItem
from aura_backend.domain.enums import ReelItemKind
from aura_backend.events import bus as event_bus
from aura_backend.realtime.hub import WebSocketHub, get_hub, reset_hub, set_hub
from aura_backend.realtime.protocol import WSRole
from aura_backend.realtime.reel_bus import (
    reel_new_video,
    reel_play_next,
    reel_play_video,
    reel_refresh_playlist,
    reel_updated,
)
from aura_backend.realtime.relay import install_relay, uninstall_relay
from aura_backend.repositories import ReelItemRepository


# ---------------------------------------------------------------------------
# domain
# ---------------------------------------------------------------------------


class TestReelItemDomain:
    def test_valid_curated(self):
        item = ReelItem(kind=ReelItemKind.CURATED, src="/videos/a.mp4", title="A", duration_sec=4.0)
        assert item.src == "/videos/a.mp4"
        assert item.kind == ReelItemKind.CURATED
        assert item.id

    def test_valid_generated(self):
        item = ReelItem(kind=ReelItemKind.GENERATED, src="/v.mp4", duration_sec=2.5)
        assert item.kind == ReelItemKind.GENERATED

    def test_kind_string_coerced(self):
        item = ReelItem(kind="generated", src="/v.mp4")  # type: ignore[arg-type]
        assert item.kind == ReelItemKind.GENERATED

    def test_src_required(self):
        with pytest.raises(ValueError):
            ReelItem(kind=ReelItemKind.CURATED, src="")

    def test_duration_must_be_positive(self):
        with pytest.raises(ValueError):
            ReelItem(kind=ReelItemKind.CURATED, src="/v.mp4", duration_sec=0)
        with pytest.raises(ValueError):
            ReelItem(kind=ReelItemKind.CURATED, src="/v.mp4", duration_sec=-1)

    def test_ids_unique(self):
        a = ReelItem(src="/a.mp4")
        b = ReelItem(src="/b.mp4")
        assert a.id != b.id


# ---------------------------------------------------------------------------
# repository
# ---------------------------------------------------------------------------


class TestReelItemRepository:
    def test_add_get(self, db_session):
        repo = ReelItemRepository(db_session)
        item = ReelItem(kind=ReelItemKind.CURATED, src="/videos/a.mp4", title="A", duration_sec=4.0)
        saved = repo.add(item)
        db_session.commit()
        fetched = repo.get(saved.id)
        assert fetched is not None
        assert fetched.src == "/videos/a.mp4"
        assert fetched.title == "A"
        assert fetched.kind == ReelItemKind.CURATED

    def test_get_missing_returns_none(self, db_session):
        repo = ReelItemRepository(db_session)
        assert repo.get("nope") is None

    def test_list_ordered(self, db_session):
        repo = ReelItemRepository(db_session)
        a = repo.add(ReelItem(src="/a.mp4", title="a"))
        db_session.commit()
        time.sleep(0.01)
        b = repo.add(ReelItem(src="/b.mp4", title="b"))
        db_session.commit()
        items = repo.list()
        ids = [i.id for i in items]
        assert a.id in ids and b.id in ids
        # Ordered by created_at ascending.
        assert ids.index(a.id) < ids.index(b.id)

    def test_remove(self, db_session):
        repo = ReelItemRepository(db_session)
        saved = repo.add(ReelItem(src="/gone.mp4"))
        db_session.commit()
        repo.remove(saved.id)
        db_session.commit()
        assert repo.get(saved.id) is None

    def test_remove_missing_no_error(self, db_session):
        repo = ReelItemRepository(db_session)
        repo.remove("missing-id")  # must not raise

    def test_generated_roundtrip(self, db_session):
        repo = ReelItemRepository(db_session)
        saved = repo.add(ReelItem(kind=ReelItemKind.GENERATED, src="/gen/x.mp4", duration_sec=6.0))
        db_session.commit()
        fetched = repo.get(saved.id)
        assert fetched is not None and fetched.kind == ReelItemKind.GENERATED
        assert fetched.duration_sec == 6.0


# ---------------------------------------------------------------------------
# reel_bus helper shapes
# ---------------------------------------------------------------------------


class TestReelBusShapes:
    def test_new_video_shape(self):
        ev = reel_new_video(job_id="j1", video_id="v1", src="/v.mp4", duration_sec=4.0, theme_id="aurora")
        assert ev["type"] == "new_video_available"
        assert ev["job_id"] == "j1"
        assert ev["video_id"] == "v1"
        assert ev["src"] == "/v.mp4"
        assert ev["duration_sec"] == 4.0
        assert ev["theme_id"] == "aurora"

    def test_updated_shape(self):
        ev = reel_updated([{"id": "v1"}], 1)
        assert ev["type"] == "reel_updated"
        assert ev["items"] == [{"id": "v1"}]
        assert ev["queue_length"] == 1

    def test_play_next_shape(self):
        assert reel_play_next() == {"type": "play_next"}

    def test_play_video_shape(self):
        assert reel_play_video("v9") == {"type": "play_video", "video_id": "v9"}

    def test_refresh_shape(self):
        assert reel_refresh_playlist() == {"type": "refresh_playlist"}


# ---------------------------------------------------------------------------
# relay fan-out (unit, hub inspection)
# ---------------------------------------------------------------------------


class _FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, payload):
        self.sent.append(payload)


async def _register_all(hub: WebSocketHub):
    d1 = _FakeWS()
    d2 = _FakeWS()
    op = _FakeWS()
    await hub.register(role=WSRole.DISPLAY1, websocket=d1, kiosk_id="k1")  # type: ignore[arg-type]
    await hub.register(role=WSRole.DISPLAY2, websocket=d2, stage_id="s1")  # type: ignore[arg-type]
    await hub.register(role=WSRole.OPERATOR, websocket=op, operator_id="c")  # type: ignore[arg-type]
    return d1, d2, op


class TestRelayFanout:
    async def test_reel_events_reach_display2_and_operator_not_display1(self):
        hub = WebSocketHub()
        set_hub(hub)
        uninstall_relay()
        install_relay()
        try:
            d1, d2, op = await _register_all(hub)
            await event_bus.publish(
                "reel",
                reel_new_video(job_id="j", video_id="v1", src="/v.mp4", duration_sec=4.0, theme_id="aurora"),
            )
            await event_bus.publish("reel", reel_play_next())
            await event_bus.publish("reel", reel_play_video("v1"))
            await event_bus.publish("reel", reel_refresh_playlist())
            await event_bus.publish("reel", reel_updated([], 0))

            d2_types = {m.get("type") for m in d2.sent}
            op_types = {m.get("type") for m in op.sent}
            d1_types = {m.get("type") for m in d1.sent}
            for expected in {
                "NEW_VIDEO_AVAILABLE", "PLAY_NEXT", "PLAY_VIDEO", "REFRESH_PLAYLIST", "REEL_UPDATED",
            }:
                assert expected in d2_types, f"{expected} missing on display2: {d2_types}"
                assert expected in op_types, f"{expected} missing on operator: {op_types}"
                assert expected not in d1_types, f"{expected} leaked to display1"
        finally:
            uninstall_relay()
            reset_hub()
            from aura_backend.realtime.relay import install_relay as _re

            _re()

    async def test_unknown_reel_type_dropped(self):
        hub = WebSocketHub()
        set_hub(hub)
        uninstall_relay()
        install_relay()
        try:
            d1, d2, op = await _register_all(hub)
            await event_bus.publish("reel", {"type": "bogus_type"})
            assert d1.sent == [] and d2.sent == [] and op.sent == []
        finally:
            uninstall_relay()
            reset_hub()
            from aura_backend.realtime.relay import install_relay as _re

            _re()

    async def test_job_events_do_not_reach_display2(self):
        hub = WebSocketHub()
        set_hub(hub)
        uninstall_relay()
        install_relay()
        try:
            d1, d2, op = await _register_all(hub)
            # Display2 has no job subscription; job events go to operator + job channels only.
            await event_bus.publish(
                "jobs",
                {"type": "job_progress", "job_id": "j1", "session_id": "s1", "progress": 0.5},
            )
            # Operator should see it (as GENERATION_PROGRESS); display2 must not.
            op_types = {m.get("type") for m in op.sent}
            d2_types = {m.get("type") for m in d2.sent}
            assert "GENERATION_PROGRESS" in op_types
            assert "GENERATION_PROGRESS" not in d2_types
        finally:
            uninstall_relay()
            reset_hub()
            from aura_backend.realtime.relay import install_relay as _re

            _re()


# ---------------------------------------------------------------------------
# display2 delivery via TestClient WS (mirrors test_realtime heartbeat pattern)
# ---------------------------------------------------------------------------


import aura_backend.realtime.routes as _ws_routes  # noqa: E402

_ws_routes.DEFAULT_HEARTBEAT_SEC = 0.05


def _hello(ws):
    import time as _t

    deadline = _t.monotonic() + 5.0
    while _t.monotonic() < deadline:
        try:
            msg = ws.receive_json()
        except Exception:
            break
        if msg is None:
            break
        if msg.get("type") == "hello":
            return msg
    pytest.fail("expected hello envelope")


def _drain(ws, timeout: float = 1.5):
    import time as _t

    out = []
    deadline = _t.monotonic() + timeout
    while _t.monotonic() < deadline:
        try:
            msg = ws.receive_json()
        except Exception:
            break
        if msg is None:
            break
        out.append(msg)
    return out


def _first(ws, target: str, timeout: float = 3.0):
    import time as _t

    deadline = _t.monotonic() + timeout
    while _t.monotonic() < deadline:
        try:
            msg = ws.receive_json()
        except Exception:
            return None
        if msg is None:
            return None
        if msg.get("type") == target:
            return msg
    return None


class TestDisplay2Delivery:
    async def test_play_next_reaches_display2_not_display1(self, client):
        with client.websocket_connect("/ws/v1/display1/k_reel1?token=kiosk-dev-token") as d1_ws:
            _hello(d1_ws)
            with client.websocket_connect("/ws/v1/display2/stage_reel1?token=kiosk-dev-token") as d2_ws:
                _hello(d2_ws)
                await event_bus.publish("reel", reel_play_next())
                await event_bus.publish("reel", reel_play_video("vid-1"))
                d2_types = [m.get("type") for m in _drain(d2_ws)]
                assert "PLAY_NEXT" in d2_types
                assert "PLAY_VIDEO" in d2_types
                d1_types = [m.get("type") for m in _drain(d1_ws, timeout=1.0)]
                assert "PLAY_NEXT" not in d1_types
                assert "PLAY_VIDEO" not in d1_types

    async def test_new_video_reaches_display2_and_operator(self, client):
        with client.websocket_connect("/ws/v1/display2/stage_reel2?token=kiosk-dev-token") as d2_ws:
            _hello(d2_ws)
            with client.websocket_connect("/ws/v1/operator?token=kiosk-dev-token") as op_ws:
                _hello(op_ws)
                await event_bus.publish(
                    "reel",
                    reel_new_video(
                        job_id="j9", video_id="v9", src="/gen.mp4", duration_sec=4.0, theme_id="pulse"
                    ),
                )
                d2_types = [m.get("type") for m in _drain(d2_ws)]
                op_types = [m.get("type") for m in _drain(op_ws)]
                assert "NEW_VIDEO_AVAILABLE" in d2_types
                assert "NEW_VIDEO_AVAILABLE" in op_types

    async def test_failed_video_removed_then_play_next_advances(self, client, db_session):
        """Backend side of playback failure: remove failed item, broadcast updated + play_next."""
        repo = ReelItemRepository(db_session)
        good = repo.add(ReelItem(kind=ReelItemKind.GENERATED, src="/gen/good.mp4", title="good"))
        bad = repo.add(ReelItem(kind=ReelItemKind.GENERATED, src="/gen/bad.mp4", title="bad"))
        db_session.commit()
        # Simulate player reporting failure for `bad`: remove it.
        repo.remove(bad.id)
        db_session.commit()
        assert repo.get(bad.id) is None
        remaining = repo.list()
        assert {i.id for i in remaining} == {good.id}

        with client.websocket_connect("/ws/v1/display2/stage_fail?token=kiosk-dev-token") as d2_ws:
            _hello(d2_ws)
            await event_bus.publish(
                "reel",
                reel_updated(
                    [{"id": i.id, "src": i.src} for i in remaining],
                    queue_length=len(remaining),
                ),
            )
            await event_bus.publish("reel", reel_play_next())
            msgs = _drain(d2_ws, timeout=2.0)
            by_type = {m.get("type"): m for m in msgs}
            assert "REEL_UPDATED" in by_type
            assert "PLAY_NEXT" in by_type
            updated = by_type["REEL_UPDATED"]
            assert updated["queue_length"] == 1
            assert all(item["id"] != bad.id for item in updated["items"])

    async def test_operator_play_video_reaches_display2(self, client):
        with client.websocket_connect("/ws/v1/operator?token=kiosk-dev-token") as op_ws:
            _hello(op_ws)
            with client.websocket_connect("/ws/v1/display2/stage_ctrl?token=kiosk-dev-token") as d2_ws:
                _hello(d2_ws)
                op_ws.send_json({"type": "play_video", "video_id": "vid-xyz"})
                _first(op_ws, "control_ack", timeout=2.0)
                msgs = [m for m in _drain(d2_ws, timeout=2.0) if m.get("type") == "PLAY_VIDEO"]
                assert msgs and msgs[0]["video_id"] == "vid-xyz"
