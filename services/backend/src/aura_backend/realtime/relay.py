"""Bridge between the internal in-process event bus and the WS hub.

The rest of the application publishes events via `events.bus.publish("jobs", {...})`
or `events.bus.publish("reel", {...})`. This module listens on those channels
and translates the events into the WebSocket protocol envelopes,
fanning them out to the right role.

To avoid coupling, we DO NOT import business modules here. Instead we
inspect the event payload and route based on the event type and the
`target_roles` hint (if the publisher set one).
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Awaitable, Callable

from ..events import bus as event_bus
from ..logging import get_logger
from .hub import WebSocketHub, envelope, get_hub
from .protocol import (
    DISPLAY1_EVENT_TYPES,
    DISPLAY2_EVENT_TYPES,
    WSRole,
)

log = get_logger("aura.realtime.relay")

# Track installed subscriptions for clean teardown.
_installed_unsubs: list[Callable[[], None]] = []

# Mapping from internal event types to the external protocol types.
# Internal types (lower-snake) -> external types (UPPER_SNAKE).
_INTERNAL_TO_DISPLAY1: dict[str, str] = {
    "job_started": "GENERATION_STARTED",
    "job_progress": "GENERATION_PROGRESS",
    "job_completed": "GENERATION_COMPLETED",
    "job_failed": "GENERATION_FAILED",
    "job_queued": "GENERATION_STARTED",
}

_INTERNAL_TO_DISPLAY2: dict[str, str] = {
    "reel_updated": "REEL_UPDATED",
    "new_video_available": "NEW_VIDEO_AVAILABLE",
    "play_next": "PLAY_NEXT",
    "play_video": "PLAY_VIDEO",
    "refresh_playlist": "REFRESH_PLAYLIST",
}


def build_relay_handlers(hub: WebSocketHub) -> dict[str, Callable[[dict[str, Any]], Awaitable[None]]]:
    """Return subscriber callables for each internal channel."""

    async def _jobs_subscriber(event: dict[str, Any]) -> None:
        await _fan_out_job_event(hub, event)

    async def _reel_subscriber(event: dict[str, Any]) -> None:
        await _fan_out_reel_event(hub, event)

    return {
        "jobs": _jobs_subscriber,
        "reel": _reel_subscriber,
    }


def install_relay(hub: WebSocketHub | None = None) -> list[Callable[[], None]]:
    """Subscribe to internal bus channels and return unsubscribe callables."""
    hub = hub or get_hub()
    handlers = build_relay_handlers(hub)
    unsubs: list[Callable[[], None]] = []
    for channel, handler in handlers.items():
        unsub = event_bus.subscribe(channel, handler)
        unsubs.append(unsub)
    global _installed_unsubs
    _installed_unsubs.extend(unsubs)
    return unsubs


def uninstall_relay() -> None:
    """Remove all installed relay subscriptions (tests)."""
    global _installed_unsubs
    for unsub in _installed_unsubs:
        with contextlib.suppress(Exception):
            unsub()
    _installed_unsubs.clear()


async def _fan_out_job_event(hub: WebSocketHub, event: dict[str, Any]) -> None:
    internal_type = event.get("type", "")
    external_type = _INTERNAL_TO_DISPLAY1.get(internal_type)
    if external_type is None:
        return  # not a Display1 event

    # Honor explicit role targeting if the publisher set one.
    target_roles = event.get("target_roles")
    if target_roles is not None and WSRole.DISPLAY1.value not in target_roles:
        # Even if not targeted at Display1, still forward to operator.
        if WSRole.OPERATOR.value not in target_roles:
            return

    job_id = event.get("job_id")
    envelope_obj = envelope(
        external_type,
        role=WSRole.DISPLAY1.value,
        job_id=job_id,
        session_id=event.get("session_id"),
        provider_id=event.get("provider_id"),
        provider_job_id=event.get("provider_job_id"),
        attempt=event.get("attempt"),
        progress=event.get("progress"),
        phase=event.get("phase"),
        detail=event.get("detail"),
        output_ref=event.get("output_ref"),
        duration_sec=event.get("duration_sec"),
        code=event.get("code"),
        message=event.get("message"),
        transient=event.get("transient", False),
    )
    # Always resolve the hub dynamically (tests swap the global hub).
    hub = get_hub()
    # Send to operator (always).
    await hub.send_to_role(WSRole.OPERATOR, envelope_obj)
    # Send to Display1 connections subscribed to this job OR this session.
    if job_id:
        await hub.send_to_channel(f"job:{job_id}", envelope_obj)
    session_id = event.get("session_id")
    if session_id:
        await hub.send_to_channel(f"session:{session_id}", envelope_obj)


async def _fan_out_reel_event(hub: WebSocketHub, event: dict[str, Any]) -> None:
    internal_type = event.get("type", "")
    external_type = _INTERNAL_TO_DISPLAY2.get(internal_type)
    if external_type is None:
        return

    envelope_obj = envelope(
        external_type,
        role=WSRole.DISPLAY2.value,
        job_id=event.get("job_id"),
        video_id=event.get("video_id"),
        src=event.get("src"),
        duration_sec=event.get("duration_sec"),
        theme_id=event.get("theme_id"),
        items=event.get("items"),
        queue_length=event.get("queue_length"),
    )
    hub = get_hub()
    await hub.send_to_role(WSRole.OPERATOR, envelope_obj)
    await hub.send_to_role(WSRole.DISPLAY2, envelope_obj)


async def hub_event_stream() -> None:
    """Legacy entrypoint kept for back-compat.

    Installs the relay handlers once and then idles; the relay itself
    runs synchronously via the in-process bus.
    """
    install_relay()
    # Keep the coroutine alive so lifespan can await / cancel it.
    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        return


async def start_event_relay() -> asyncio.Task[None]:
    """Start the relay as a background task (legacy)."""
    return asyncio.create_task(hub_event_stream())


# Auto-install the relay handlers on import so the WebSocket hub
# receives events published via the in-process bus. Production overrides
# this through the lifespan, but the default behaviour is harmless: the
# same hub instance is used.
install_relay()