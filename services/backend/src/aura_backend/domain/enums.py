"""Domain enums and FSM transition tables.

Pure constants. Importing this module must not trigger any I/O.
"""

from __future__ import annotations

import enum
from typing import FrozenSet


class SessionState(str, enum.Enum):
    """Visitor session lifecycle."""

    IDLE = "IDLE"
    LANGUAGE_SELECTED = "LANGUAGE_SELECTED"
    THEME_SELECTED = "THEME_SELECTED"
    COUNTDOWN = "COUNTDOWN"
    CAPTURING = "CAPTURING"
    UPLOADED = "UPLOADED"
    GENERATING = "GENERATING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class GenerationJobState(str, enum.Enum):
    """AI video-generation job lifecycle."""

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    GENERATING = "GENERATING"
    POST_PROCESSING = "POST_PROCESSING"
    ENCODING = "ENCODING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


class ReelItemKind(str, enum.Enum):
    CURATED = "curated"
    GENERATED = "generated"


class JobTransitionError(ValueError):
    """Raised when a GenerationJob state transition is illegal."""

    def __init__(self, frm: str, to: str) -> None:
        super().__init__(f"Illegal generation job transition: {frm} -> {to}")
        self.frm = frm
        self.to = to


class SessionTransitionError(ValueError):
    """Raised when a Session state transition is illegal."""

    def __init__(self, frm: str, to: str) -> None:
        super().__init__(f"Illegal session transition: {frm} -> {to}")
        self.frm = frm
        self.to = to


# ---- Session FSM ----
_SESSION_TRANSITIONS: dict[SessionState, FrozenSet[SessionState]] = {
    SessionState.IDLE: frozenset({SessionState.LANGUAGE_SELECTED}),
    SessionState.LANGUAGE_SELECTED: frozenset({SessionState.THEME_SELECTED}),
    SessionState.THEME_SELECTED: frozenset({SessionState.COUNTDOWN}),
    SessionState.COUNTDOWN: frozenset({SessionState.CAPTURING}),
    SessionState.CAPTURING: frozenset({SessionState.UPLOADED}),
    SessionState.UPLOADED: frozenset({SessionState.GENERATING}),
    SessionState.GENERATING: frozenset({SessionState.COMPLETED, SessionState.ERROR}),
    SessionState.COMPLETED: frozenset({SessionState.IDLE}),
    SessionState.ERROR: frozenset({SessionState.IDLE}),
}


def assert_session_transition(frm: SessionState, to: SessionState) -> None:
    allowed = _SESSION_TRANSITIONS.get(frm, frozenset())
    if to not in allowed:
        raise SessionTransitionError(frm.value, to.value)


def allowed_session_targets(frm: SessionState) -> frozenset[SessionState]:
    return _SESSION_TRANSITIONS.get(frm, frozenset())


# ---- GenerationJob FSM ----
#
# Notes:
# - CREATED is the immediate post-creation state (before the queue accepts it).
# - QUEUED means the job has been handed to a worker queue.
# - PROCESSING / GENERATING / POST_PROCESSING / ENCODING are worker-internal phases.
# - Terminal states: COMPLETED, FAILED, CANCELLED, TIMEOUT.
# - CANCELLED is reachable from any non-terminal state.
# - TIMEOUT is a special failure state set by the worker when the deadline elapses.
#
_GENERATION_TRANSITIONS: dict[GenerationJobState, FrozenSet[GenerationJobState]] = {
    GenerationJobState.CREATED: frozenset(
        {GenerationJobState.QUEUED, GenerationJobState.CANCELLED, GenerationJobState.FAILED}
    ),
    GenerationJobState.QUEUED: frozenset(
        {
            GenerationJobState.PROCESSING,
            GenerationJobState.CANCELLED,
            GenerationJobState.FAILED,
            GenerationJobState.TIMEOUT,
        }
    ),
    GenerationJobState.PROCESSING: frozenset(
        {
            GenerationJobState.GENERATING,
            GenerationJobState.CANCELLED,
            GenerationJobState.FAILED,
            GenerationJobState.TIMEOUT,
        }
    ),
    GenerationJobState.GENERATING: frozenset(
        {
            GenerationJobState.POST_PROCESSING,
            GenerationJobState.CANCELLED,
            GenerationJobState.FAILED,
            GenerationJobState.TIMEOUT,
        }
    ),
    GenerationJobState.POST_PROCESSING: frozenset(
        {
            GenerationJobState.ENCODING,
            GenerationJobState.CANCELLED,
            GenerationJobState.FAILED,
            GenerationJobState.TIMEOUT,
        }
    ),
    GenerationJobState.ENCODING: frozenset(
        {
            GenerationJobState.COMPLETED,
            GenerationJobState.CANCELLED,
            GenerationJobState.FAILED,
            GenerationJobState.TIMEOUT,
        }
    ),
    # Terminal states have no outgoing transitions.
    GenerationJobState.COMPLETED: frozenset(),
    GenerationJobState.FAILED: frozenset(),
    GenerationJobState.CANCELLED: frozenset(),
    GenerationJobState.TIMEOUT: frozenset(),
}


def assert_generation_transition(
    frm: GenerationJobState, to: GenerationJobState
) -> None:
    allowed = _GENERATION_TRANSITIONS.get(frm, frozenset())
    if to not in allowed:
        raise JobTransitionError(frm.value, to.value)


def allowed_generation_targets(frm: GenerationJobState) -> frozenset[GenerationJobState]:
    return _GENERATION_TRANSITIONS.get(frm, frozenset())


def is_terminal_generation_state(s: GenerationJobState) -> bool:
    return s in {
        GenerationJobState.COMPLETED,
        GenerationJobState.FAILED,
        GenerationJobState.CANCELLED,
        GenerationJobState.TIMEOUT,
    }