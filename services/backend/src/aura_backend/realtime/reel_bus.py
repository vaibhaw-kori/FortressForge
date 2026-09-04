"""Reel control: thin helper that publishes reel events via the
internal event bus. Kept separate from WS code so the worker and
operator UI can publish without importing the hub."""

from __future__ import annotations

import asyncio
from typing import Any

from ..events import bus as event_bus


async def publish_reel_event(event: dict[str, Any]) -> None:
    """Publish a reel event to the in-process bus.

    Relays translate these into WebSocket envelopes for Display 2 + operator.
    """
    await event_bus.publish("reel", event)


def publish_reel_event_sync(event: dict[str, Any]) -> None:
    """Sync version for code paths that aren't inside an event loop."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(event_bus.publish("reel", event))
    except RuntimeError:
        # No running loop — best-effort: create one briefly.
        try:
            asyncio.run(event_bus.publish("reel", event))
        except Exception:  # noqa: BLE001
            pass


def reel_new_video(
    *,
    job_id: str,
    video_id: str,
    src: str,
    duration_sec: float,
    theme_id: str,
) -> dict[str, Any]:
    return {
        "type": "new_video_available",
        "job_id": job_id,
        "video_id": video_id,
        "src": src,
        "duration_sec": duration_sec,
        "theme_id": theme_id,
    }


def reel_updated(items: list[dict[str, Any]], queue_length: int) -> dict[str, Any]:
    return {
        "type": "reel_updated",
        "items": items,
        "queue_length": queue_length,
    }


def reel_play_next() -> dict[str, Any]:
    return {"type": "play_next"}


def reel_play_video(video_id: str) -> dict[str, Any]:
    return {"type": "play_video", "video_id": video_id}


def reel_refresh_playlist() -> dict[str, Any]:
    return {"type": "refresh_playlist"}