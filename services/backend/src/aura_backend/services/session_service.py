"""Session service: lifecycle, capture handoff, generation handoff."""

from __future__ import annotations

from sqlalchemy.orm import Session as OrmSession

from ..domain import Session
from ..errors import NotFoundError
from ..repositories import SessionRepository


class SessionService:
    def __init__(self, db: OrmSession) -> None:
        self._db = db
        self._repo = SessionRepository(db)

    def create(self, language: str | None = None) -> Session:
        s = Session()
        if language:
            s.select_language(language)
        self._repo.add(s)
        return s

    def get(self, session_id: str) -> Session:
        s = self._repo.get(session_id)
        if s is None:
            raise NotFoundError(f"Session {session_id} not found")
        return s

    def list(self) -> list[Session]:
        return self._repo.list()

    def select_language(self, session_id: str, language: str) -> Session:
        s = self.get(session_id)
        s.select_language(language)
        return self._repo.update(s)

    def select_theme(self, session_id: str, theme_id: str) -> Session:
        s = self.get(session_id)
        s.select_theme(theme_id)
        return self._repo.update(s)

    def start_countdown(self, session_id: str) -> Session:
        s = self.get(session_id)
        s.start_countdown()
        return self._repo.update(s)

    def start_capture(self, session_id: str) -> Session:
        s = self.get(session_id)
        s.start_capture()
        return self._repo.update(s)

    def mark_uploaded(self, session_id: str, capture_ref: str) -> Session:
        s = self.get(session_id)
        s.mark_uploaded(capture_ref)
        return self._repo.update(s)

    def mark_generating(self, session_id: str) -> Session:
        s = self.get(session_id)
        # Let the FSM raise SessionTransitionError (-> 409) if not allowed.
        s.mark_generating()
        return self._repo.update(s)

    def mark_completed(self, session_id: str) -> Session:
        s = self.get(session_id)
        s.mark_completed()
        return self._repo.update(s)

    def mark_error(self, session_id: str) -> Session:
        s = self.get(session_id)
        s.mark_error()
        return self._repo.update(s)

    def reset(self, session_id: str) -> Session:
        s = self.get(session_id)
        s.reset()
        return self._repo.update(s)