"""WebSocket endpoints for Displays 1, 2, and the operator console.

Endpoints:
- WS /ws/v1/display1/{kiosk_id}     -> Display 1 (kiosk)
- WS /ws/v1/display2/{stage_id}     -> Display 2 (stage)
- WS /ws/v1/operator                 -> operator console
- WS /ws/v1/job/{job_id}             -> per-job fan-out (display 1 watch)

All endpoints share the same lifecycle:
1. Validate auth token (kiosk or operator JWT).
2. Accept the socket and register with the hub.
3. Send `hello` envelope + replay any missed events (last_event_id).
4. Loop reading client messages (ping/pong, subscribe, control).
5. Heartbeat: server sends periodic ping; client replies with pong.
6. Idle timeout closes stale connections.
7. Graceful disconnect cleans up subscriptions + channel membership.

No business logic here — we only translate frames in/out and delegate
to the hub.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..config import get_settings
from ..events import bus as event_bus
from ..logging import get_logger
from .hub import WebSocketHub, get_hub
from .protocol import (
    DEFAULT_HEARTBEAT_SEC,
    DEFAULT_IDLE_TIMEOUT_SEC,
    PROTOCOL_VERSION,
    WSRole,
    channel_job,
    channel_session,
    make_envelope,
    parse_client_message,
)

router = APIRouter()
log = get_logger("aura.ws")


# ---- shared lifecycle ----


async def _serve_endpoint(
    ws: WebSocket,
    *,
    role: WSRole,
    hub: WebSocketHub,
    connection_id: str | None,
    require_token: str | None,
    init_channels: list[str],
    init_kwargs: dict[str, Any],
) -> None:
    s = get_settings()
    if require_token and require_token != s.kiosk_token_default:
        await ws.close(code=4401)
        return

    await ws.accept()
    conn = await hub.register(
        role=role,
        websocket=ws,
        connection_id=connection_id,
        channels=init_channels,
        **init_kwargs,
    )

    # Send hello.
    try:
        await ws.send_json(
            make_envelope(
                "hello",
                role=role.value,
                connection_id=conn.connection_id,
                v=PROTOCOL_VERSION,
                heartbeat_sec=DEFAULT_HEARTBEAT_SEC,
                idle_timeout_sec=DEFAULT_IDLE_TIMEOUT_SEC,
                channels=sorted(conn.channels),
            )
        )
    except Exception:  # noqa: BLE001
        await hub.unregister(conn.connection_id)
        return

    # Replay any buffered events the client may have missed.
    missed = hub.events_after(conn.last_event_id)
    for ev in missed:
        with contextlib.suppress(Exception):
            await ws.send_json(ev)

    # Heartbeat task: server-initiated pings every heartbeat_sec.
    heartbeat_task = asyncio.create_task(_heartbeat_loop(ws, hub, conn.connection_id))

    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    ws.receive_text(),
                    timeout=DEFAULT_HEARTBEAT_SEC,
                )
            except asyncio.TimeoutError:
                # No client message in time; rely on heartbeat to nudge.
                continue
            await hub.record_activity(conn.connection_id)
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json(make_envelope("error", reason="invalid_json"))
                continue
            try:
                msg_type, payload = parse_client_message(parsed)
            except ValueError as exc:
                await ws.send_json(make_envelope("error", reason=str(exc)))
                continue

            await _handle_client_message(
                hub=hub,
                ws=ws,
                role=role,
                connection_id=conn.connection_id,
                msg_type=msg_type,
                payload=payload,
            )
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        log.warning("ws_loop_error", role=role.value, error=str(exc))
    finally:
        heartbeat_task.cancel()
        with contextlib.suppress(Exception):
            await heartbeat_task
        await hub.unregister(conn.connection_id)


async def _heartbeat_loop(ws: WebSocket, hub: WebSocketHub, connection_id: str) -> None:
    try:
        while True:
            await asyncio.sleep(DEFAULT_HEARTBEAT_SEC)
            try:
                await ws.send_json(
                    make_envelope(
                        "ping",
                        ts=datetime.now(timezone.utc).isoformat(),
                    )
                )
                await hub.record_activity(connection_id)
            except Exception:  # noqa: BLE001
                return
    except asyncio.CancelledError:
        return


async def _handle_client_message(
    *,
    hub: WebSocketHub,
    ws: WebSocket,
    role: WSRole,
    connection_id: str,
    msg_type: str,
    payload: dict[str, Any],
) -> None:
    if msg_type == "pong":
        await hub.record_activity(connection_id)
        return

    if msg_type == "hello":
        # Re-hello after reconnect: update client metadata.
        if "client_id" in payload:
            await _set_attr(hub, connection_id, client_id=payload["client_id"])
        if "last_event_id" in payload:
            await hub.set_last_event_id(connection_id, payload["last_event_id"])
            # Send hello_ack FIRST so the client can correlate, then replay missed events.
            await ws.send_json(make_envelope("hello_ack", connection_id=connection_id))
            missed = hub.events_after(payload["last_event_id"])
            for ev in missed:
                with contextlib.suppress(Exception):
                    await ws.send_json(ev)
            return
        await ws.send_json(make_envelope("hello_ack", connection_id=connection_id))
        return

    if msg_type == "ack":
        eid = payload.get("last_event_id")
        if isinstance(eid, str):
            await hub.set_last_event_id(connection_id, eid)
        return

    if msg_type == "subscribe":
        job_id = payload.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            await ws.send_json(make_envelope("error", reason="missing_job_id"))
            return
        await hub.subscribe_job(connection_id, job_id)
        await ws.send_json(make_envelope("subscribed", job_id=job_id))
        return

    if msg_type == "unsubscribe":
        job_id = payload.get("job_id")
        if isinstance(job_id, str) and job_id:
            await hub.unsubscribe_job(connection_id, job_id)
            await ws.send_json(make_envelope("unsubscribed", job_id=job_id))
        return

    if msg_type in ("play_next", "play_video", "refresh_playlist"):
        # Re-broadcast the control command to the appropriate role so
        # the operator UI and other Display2 clients can react.
        target_role = WSRole.DISPLAY2
        await bus_publish_control(target_role, msg_type, payload)
        await ws.send_json(make_envelope("control_ack", type=msg_type))
        return

    # Unknown message type — surface a structured error envelope.
    await ws.send_json(make_envelope("error", reason=f"unknown_type:{msg_type}"))


async def _set_attr(hub: WebSocketHub, connection_id: str, **fields: Any) -> None:
    async with hub._lock:  # noqa: SLF001 - simple update
        conn = hub._connections.get(connection_id)  # noqa: SLF001
        if conn is None:
            return
        for k, v in fields.items():
            if hasattr(conn, k):
                setattr(conn, k, v)


async def bus_publish_control(
    target_role: WSRole, msg_type: str, payload: dict[str, Any]
) -> None:
    """Forward a client-issued control command back through the relay."""
    event = {
        "type": msg_type,
        "target_roles": [target_role.value, WSRole.OPERATOR.value],
        "video_id": payload.get("video_id"),
    }
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(event_bus.publish("reel", event))
    except RuntimeError:
        pass


# ---- endpoint registrations ----


@router.websocket("/ws/v1/display1/{kiosk_id}")
async def ws_display1(
    ws: WebSocket,
    kiosk_id: str,
    token: str | None = Query(default=None),
) -> None:
    """Display 1 (kiosk). Receives GENERATION_* events for jobs/sessions
    it is associated with. Optionally subscribes to per-job updates
    via `subscribe` messages.
    """
    await _serve_endpoint(
        ws,
        role=WSRole.DISPLAY1,
        hub=get_hub(),
        connection_id=None,
        require_token=token,
        init_channels=[],
        init_kwargs={"kiosk_id": kiosk_id},
    )


@router.websocket("/ws/v1/display2/{stage_id}")
async def ws_display2(
    ws: WebSocket,
    stage_id: str,
    token: str | None = Query(default=None),
) -> None:
    """Display 2 (stage). Receives REEL_*, NEW_VIDEO_AVAILABLE, PLAY_*
    events. Sends `play_next`/`play_video`/`refresh_playlist` to
    broadcast control commands.
    """
    await _serve_endpoint(
        ws,
        role=WSRole.DISPLAY2,
        hub=get_hub(),
        connection_id=None,
        require_token=token,
        init_channels=[],
        init_kwargs={"stage_id": stage_id},
    )


@router.websocket("/ws/v1/operator")
async def ws_operator(
    ws: WebSocket,
    token: str | None = Query(default=None),
) -> None:
    """Operator console: receives everything (Display 1 + Display 2)."""
    await _serve_endpoint(
        ws,
        role=WSRole.OPERATOR,
        hub=get_hub(),
        connection_id=None,
        require_token=token,
        init_channels=[],
        init_kwargs={"operator_id": "console"},
    )


@router.websocket("/ws/v1/job/{job_id}")
async def ws_job(
    ws: WebSocket,
    job_id: str,
    token: str | None = Query(default=None),
) -> None:
    """Per-job channel. Subscribes the connecting socket to events for
    the given job. Available for any role (operator, kiosk, stage).
    """
    init_channels = [channel_job(job_id)]
    await _serve_endpoint(
        ws,
        role=WSRole.OPERATOR,  # acts as a passive observer
        hub=get_hub(),
        connection_id=None,
        require_token=token,
        init_channels=init_channels,
        init_kwargs={"operator_id": f"job:{job_id}"},
    )


# Legacy routes kept so existing tests (and the old frontend) still work.
@router.websocket("/ws/jobs")
async def ws_jobs_legacy(
    ws: WebSocket, token: str | None = Query(default=None)
) -> None:
    """Back-compat: `/ws/jobs` is an alias for the operator channel."""
    await ws_operator(ws, token=token)


@router.websocket("/ws/jobs/{job_id}")
async def ws_job_legacy(
    ws: WebSocket, job_id: str, token: str | None = Query(default=None)
) -> None:
    """Back-compat: `/ws/jobs/{job_id}` is an alias for `/ws/v1/job/{job_id}`."""
    await ws_job(ws, job_id=job_id, token=token)