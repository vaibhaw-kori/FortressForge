"""Session repository (SQLAlchemy-backed)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..db.mappers import session_from_domain, session_to_domain
from ..db.models import SessionRow
from ..domain import Session
from .base import Repository


class SessionRepository(Repository[Session]):
    def __init__(self, db: OrmSession) -> None:
        self._db = db

    def get(self, id: str) -> Session | None:
        row = self._db.get(SessionRow, id)
        return session_to_domain(row) if row else None

    def list(self) -> list[Session]:
        rows = self._db.execute(select(SessionRow).order_by(SessionRow.created_at.desc())).scalars()
        return [session_to_domain(r) for r in rows]

    def add(self, item: Session) -> Session:
        row = SessionRow(**session_from_domain(item))
        self._db.add(row)
        self._db.flush()
        return session_to_domain(row)

    def remove(self, id: str) -> None:
        row = self._db.get(SessionRow, id)
        if row is not None:
            self._db.delete(row)

    def update(self, item: Session) -> Session:
        row = self._db.get(SessionRow, item.id)
        if row is None:
            return self.add(item)
        data = session_from_domain(item)
        for k, v in data.items():
            if k in {"created_at", "id"}:
                continue
            setattr(row, k, v)
        self._db.flush()
        return session_to_domain(row)