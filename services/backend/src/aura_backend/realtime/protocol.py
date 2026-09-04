"""WebSocket protocol: connection-level types and helpers.

Kept framework-free so the same definitions can be mirrored in the
frontend @aura/contracts package.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# ---- Roles / event taxonomy ----


class WSRole(str, enum.Enum):
    DISPLAY1 = "display1"  # kiosk
    DISPLAY2 = "display2"  # stage
    OPERATOR = "operator"


# Display1 -> Display 1 events it cares about
DISPLAY1_EVENT_TYPES: tuple[str, ...] = (
    "GENERATION_STARTED",
    "GENERATION_PROGRESS",
    "GENERATION_COMPLETED",
    "GENERATION_FAILED",
)

# Display2 events
DISPLAY2_EVENT_TYPES: tuple[str, ...] = (
    "REEL_UPDATED",
    "NEW_VIDEO_AVAILABLE",
    "PLAY_NEXT",
    "PLAY_VIDEO",
    "REFRESH_PLAYLIST",
)

OPERATOR_EVENT_TYPES: tuple[str, ...] = DISPLAY1_EVENT_TYPES + DISPLAY2_EVENT_TYPES

PROTOCOL_VERSION = 1


# ---- Envelope helpers ----


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_envelope(
    event_type: str,
    *,
    event_id: str | None = None,
    ts: str | None = None,
    role: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Build a versioned WebSocket envelope.

    Every outbound event is wrapped so the client always has:
    - v: protocol version
    - id: monotonically increasing event_id (used for replay)
    - type: event name
    - ts: ISO timestamp
    - role: which display role this event is targeting (optional)
    - ... payload fields (e.g. job_id, output_ref)
    """
    payload = {
        "v": PROTOCOL_VERSION,
        "id": event_id or uuid.uuid4().hex,
        "type": event_type,
        "ts": ts or utcnow_iso(),
    }
    if role is not None:
        payload["role"] = role
    payload.update(fields)
    return payload


# ---- Client -> Server messages ----


class ClientMessageType(str, enum.Enum):
    HELLO = "hello"
    PING = "ping"
    PONG = "pong"
    SUBSCRIBE = "subscribe"  # body: {"job_id": "..."}
    UNSUBSCRIBE = "unsubscribe"
    ACK = "ack"  # body: {"last_event_id": "..."}
    PLAY_NEXT = "play_next"
    PLAY_VIDEO = "play_video"  # body: {"video_id": "..."}
    REFRESH_PLAYLIST = "refresh_playlist"


def parse_client_message(raw: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Validate a client message.

    Returns (message_type, payload) on success.
    Raises ValueError on invalid messages.
    """
    if not isinstance(raw, dict):
        raise ValueError("message must be an object")
    msg_type = raw.get("type")
    if not isinstance(msg_type, str):
        raise ValueError("missing or invalid 'type' field")
    return msg_type, {k: v for k, v in raw.items() if k != "type"}


# ---- Connection record ----


@dataclass
class Connection:
    """Server-side bookkeeping for a single open WebSocket."""

    connection_id: str
    role: WSRole
    websocket: Any  # starlette.websockets.WebSocket; typed as Any to avoid coupling
    channels: set[str] = field(default_factory=set)
    subscribed_jobs: set[str] = field(default_factory=set)
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    client_id: str | None = None
    kiosk_id: str | None = None
    stage_id: str | None = None
    operator_id: str | None = None
    last_event_id: str | None = None
    is_alive: bool = True


# ---- Channel naming convention ----


def channel_display1(kiosk_id: str) -> str:
    return f"display1:{kiosk_id}"


def channel_display2(stage_id: str) -> str:
    return f"display2:{stage_id}"


def channel_operator(operator_id: str) -> str:
    return f"operator:{operator_id}"


def channel_job(job_id: str) -> str:
    return f"job:{job_id}"


def channel_session(session_id: str) -> str:
    return f"session:{session_id}"


# Heartbeat / timeout tuning
DEFAULT_HEARTBEAT_SEC: float = 15.0
DEFAULT_IDLE_TIMEOUT_SEC: float = 60.0
DEFAULT_REPLAY_BUFFER_SIZE: int = 256