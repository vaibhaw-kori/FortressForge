"""Session aggregate."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .enums import SessionState, SessionTransitionError, assert_session_transition


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Session:
    """Visitor session.

    A Session owns the FSM for a single visitor's interaction with Display 1:
    language -> theme -> countdown -> capture -> upload -> generate -> done.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    language: str | None = None
    theme_id: str | None = None
    state: SessionState = SessionState.IDLE
    capture_ref: str | None = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    # ---- FSM transitions ----

    def select_language(self, language: str) -> None:
        self._assert_lang(language)
        self._transition(SessionState.LANGUAGE_SELECTED)
        self.language = language
        self._touch()

    def select_theme(self, theme_id: str) -> None:
        self._assert_theme(theme_id)
        self._transition(SessionState.THEME_SELECTED)
        self.theme_id = theme_id
        self._touch()

    def start_countdown(self) -> None:
        self._transition(SessionState.COUNTDOWN)
        self._touch()

    def start_capture(self) -> None:
        self._transition(SessionState.CAPTURING)
        self._touch()

    def mark_uploaded(self, capture_ref: str) -> None:
        if not capture_ref:
            raise ValueError("capture_ref required")
        self._transition(SessionState.UPLOADED)
        self.capture_ref = capture_ref
        self._touch()

    def mark_generating(self) -> None:
        self._transition(SessionState.GENERATING)
        self._touch()

    def mark_completed(self) -> None:
        self._transition(SessionState.COMPLETED)
        self._touch()

    def mark_error(self) -> None:
        self._transition(SessionState.ERROR)
        self._touch()

    def reset(self) -> None:
        """Reset an ended session back to IDLE for reuse."""
        self._transition(SessionState.IDLE)
        self._touch()

    # ---- helpers ----

    def _transition(self, to: SessionState) -> None:
        try:
            assert_session_transition(self.state, to)
        except SessionTransitionError:
            raise
        self.state = to

    def _touch(self) -> None:
        self.updated_at = _utcnow()

    @staticmethod
    def _assert_lang(language: str) -> None:
        if not language or len(language) > 8:
            raise ValueError("language must be 1..8 chars")

    @staticmethod
    def _assert_theme(theme_id: str) -> None:
        if not theme_id or len(theme_id) > 64:
            raise ValueError("theme_id must be 1..64 chars")