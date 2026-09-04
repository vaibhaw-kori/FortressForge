"""WebSocket connection registry + hub.

Responsibilities:
- Track every active WebSocket + its role / channels / subscriptions.
- Send events to one channel, many channels, or all connections of a role.
- Maintain a small replay buffer so reconnecting clients can re-fetch
  events they missed (by last_event_id).
- Run a periodic sweeper that closes connections that haven't pinged
  within `idle_timeout_sec`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Iterable

from ..logging import get_logger
from .protocol import (
    Connection,
    DEFAULT_HEARTBEAT_SEC,
    DEFAULT_IDLE_TIMEOUT_SEC,
    DEFAULT_REPLAY_BUFFER_SIZE,
    WSRole,
    channel_display1,
    channel_display2,
    channel_job,
    channel_operator,
    channel_session,
    make_envelope,
    utcnow_iso,
)

log = get_logger("aura.realtime")


class WebSocketHub:
    def __init__(
        self,
        *,
        heartbeat_sec: float = DEFAULT_HEARTBEAT_SEC,
        idle_timeout_sec: float = DEFAULT_IDLE_TIMEOUT_SEC,
        replay_buffer_size: int = DEFAULT_REPLAY_BUFFER_SIZE,
    ) -> None:
        self._connections: dict[str, Connection] = {}
        self._channels: dict[str, set[str]] = defaultdict(set)
        self._roles: dict[WSRole, set[str]] = defaultdict(set)
        self._lock = asyncio.Lock()
        # Replay buffer: list of envelopes keyed by event_id, ordered.
        self._buffer: deque[dict[str, Any]] = deque(maxlen=replay_buffer_size)
        self._buffer_ids: set[str] = set()
        # Sweeper state
        self._heartbeat_sec = heartbeat_sec
        self._idle_timeout_sec = idle_timeout_sec
        self._sweeper_task: asyncio.Task[None] | None = None
        self._sweeper_stop = asyncio.Event()

    # ---- lifecycle ----

    async def start(self) -> None:
        if self._sweeper_task is None:
            self._sweeper_stop.clear()
            self._sweeper_task = asyncio.create_task(self._sweeper_loop())

    async def stop(self) -> None:
        self._sweeper_stop.set()
        if self._sweeper_task is not None:
            self._sweeper_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._sweeper_task
            self._sweeper_task = None
        # Close all open connections gracefully.
        async with self._lock:
            for conn in list(self._connections.values()):
                with contextlib.suppress(Exception):
                    await conn.websocket.close(code=1001, reason="server_shutdown")
            self._connections.clear()
            self._channels.clear()
            self._roles.clear()

    # ---- connection management ----

    async def register(
        self,
        *,
        role: WSRole,
        websocket: Any,
        client_id: str | None = None,
        kiosk_id: str | None = None,
        stage_id: str | None = None,
        operator_id: str | None = None,
        channels: Iterable[str] | None = None,
        connection_id: str | None = None,
    ) -> Connection:
        cid = connection_id or _new_id(f"conn-{role.value}")
        conn = Connection(
            connection_id=cid,
            role=role,
            websocket=websocket,
            client_id=client_id,
            kiosk_id=kiosk_id,
            stage_id=stage_id,
            operator_id=operator_id,
        )
        conn.channels = set(channels) if channels else set()
        if role == WSRole.DISPLAY1 and kiosk_id:
            conn.channels.add(channel_display1(kiosk_id))
        if role == WSRole.DISPLAY2 and stage_id:
            conn.channels.add(channel_display2(stage_id))
        if role == WSRole.OPERATOR and operator_id:
            conn.channels.add(channel_operator(operator_id))
        async with self._lock:
            self._connections[cid] = conn
            self._roles[role].add(cid)
            for ch in conn.channels:
                self._channels[ch].add(cid)
        return conn

    async def unregister(self, connection_id: str) -> None:
        async with self._lock:
            conn = self._connections.pop(connection_id, None)
            if conn is None:
                return
            self._roles[conn.role].discard(connection_id)
            for ch in list(conn.channels):
                self._channels[ch].discard(connection_id)
                if not self._channels[ch]:
                    self._channels.pop(ch, None)
            conn.is_alive = False

    async def subscribe_job(self, connection_id: str, job_id: str) -> None:
        async with self._lock:
            conn = self._connections.get(connection_id)
            if conn is None:
                return
            conn.subscribed_jobs.add(job_id)
            self._channels[channel_job(job_id)].add(connection_id)

    async def unsubscribe_job(self, connection_id: str, job_id: str) -> None:
        async with self._lock:
            conn = self._connections.get(connection_id)
            if conn is None:
                return
            conn.subscribed_jobs.discard(job_id)
            self._channels[channel_job(job_id)].discard(connection_id)

    async def subscribe_session(self, connection_id: str, session_id: str) -> None:
        async with self._lock:
            conn = self._connections.get(connection_id)
            if conn is None:
                return
            self._channels[channel_session(session_id)].add(connection_id)
            conn.channels.add(channel_session(session_id))

    async def record_activity(self, connection_id: str) -> None:
        async with self._lock:
            conn = self._connections.get(connection_id)
            if conn is None:
                return
            conn.last_activity_at = datetime.now(timezone.utc)
            conn.is_alive = True

    async def set_last_event_id(self, connection_id: str, event_id: str) -> None:
        async with self._lock:
            conn = self._connections.get(connection_id)
            if conn is None:
                return
            conn.last_event_id = event_id

    # ---- broadcasting ----

    async def send_to_channel(self, channel: str, envelope: dict[str, Any]) -> int:
        """Fan out to every connection subscribed to `channel`."""
        delivered = 0
        async with self._lock:
            targets = list(self._channels.get(channel, ()))
        dead: list[str] = []
        for cid in targets:
            conn = self._connections.get(cid)
            if conn is None or not conn.is_alive:
                dead.append(cid)
                continue
            try:
                await conn.websocket.send_json(envelope)
                delivered += 1
            except Exception:  # noqa: BLE001
                dead.append(cid)
        if dead:
            for cid in dead:
                await self.unregister(cid)
        self._remember_event(envelope)
        return delivered

    async def send_to_role(self, role: WSRole, envelope: dict[str, Any]) -> int:
        delivered = 0
        async with self._lock:
            targets = list(self._roles.get(role, ()))
        for cid in targets:
            conn = self._connections.get(cid)
            if conn is None or not conn.is_alive:
                continue
            try:
                await conn.websocket.send_json(envelope)
                delivered += 1
            except Exception:  # noqa: BLE001
                await self.unregister(cid)
        self._remember_event(envelope)
        return delivered

    async def send_to_connection(self, connection_id: str, envelope: dict[str, Any]) -> bool:
        async with self._lock:
            conn = self._connections.get(connection_id)
        if conn is None or not conn.is_alive:
            return False
        try:
            await conn.websocket.send_json(envelope)
            return True
        except Exception:  # noqa: BLE001
            await self.unregister(connection_id)
            return False

    # ---- replay ----

    def events_after(self, last_event_id: str | None) -> list[dict[str, Any]]:
        """Return buffered events with id > last_event_id (insertion order)."""
        if not last_event_id:
            return list(self._buffer)
        out: list[dict[str, Any]] = []
        seen_target = False
        for env in self._buffer:
            if seen_target:
                out.append(env)
                continue
            if env.get("id") == last_event_id:
                seen_target = True
        return out

    def _remember_event(self, env: dict[str, Any]) -> None:
        eid = env.get("id")
        if not eid:
            return
        if eid in self._buffer_ids:
            return
        self._buffer.append(env)
        self._buffer_ids.add(eid)
        # Keep id set bounded
        if len(self._buffer_ids) > self._buffer.maxlen * 2:
            self._buffer_ids = {e.get("id") for e in self._buffer}

    # ---- queries ----

    def connection_count(self) -> int:
        return len(self._connections)

    def connection_count_by_role(self, role: WSRole) -> int:
        return len(self._roles.get(role, ()))

    def list_connection_ids(self) -> list[str]:
        return list(self._connections.keys())

    # ---- stale cleanup sweeper ----

    async def _sweeper_loop(self) -> None:
        while not self._sweeper_stop.is_set():
            try:
                await asyncio.sleep(self._heartbeat_sec)
                await self._sweep_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                log.warning("sweeper_error", error=str(exc))

    async def _sweep_once(self) -> None:
        now = datetime.now(timezone.utc)
        stale: list[tuple[str, Connection]] = []
        async with self._lock:
            for cid, conn in self._connections.items():
                age = (now - conn.last_activity_at).total_seconds()
                if age > self._idle_timeout_sec:
                    stale.append((cid, conn))
        for cid, conn in stale:
            log.info("closing_stale_connection", connection_id=cid, role=conn.role.value)
            with contextlib.suppress(Exception):
                await conn.websocket.close(code=4408, reason="idle_timeout")
            await self.unregister(cid)


def _new_id(prefix: str) -> str:
    import uuid as _u

    return f"{prefix}-{_u.uuid4().hex[:12]}"


# ---- Module-level singleton + DI ----

_hub: WebSocketHub | None = None


def get_hub() -> WebSocketHub:
    global _hub
    if _hub is None:
        _hub = WebSocketHub()
    return _hub


def set_hub(hub: WebSocketHub | None) -> None:
    """Override the global hub (tests)."""
    global _hub
    _hub = hub


def reset_hub() -> WebSocketHub:
    """Reset the module-level hub. Used by tests to isolate state."""
    global _hub
    _hub = None
    return get_hub()


def utc_now_iso() -> str:  # pragma: no cover - trivial
    return utcnow_iso()


# Back-compat alias used by worker/reel broadcast helpers
def envelope(event_type: str, **fields: Any) -> dict[str, Any]:
    """Wrapper preserved for back-compat with existing call sites."""
    return make_envelope(event_type, **fields)