"""Experience repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..db.mappers import experience_to_domain, experience_to_row
from ..db.models import ExperienceRow
from ..domain import Experience
from .base import Repository


class ExperienceRepository(Repository[Experience]):
    def __init__(self, db: OrmSession) -> None:
        self._db = db

    def get(self, id: str) -> Experience | None:
        row = self._db.get(ExperienceRow, id)
        return experience_to_domain(row) if row else None

    def list(self, *, enabled_only: bool = False) -> list[Experience]:
        # Operator-friendly ordering: explicit display_order, then id.
        stmt = select(ExperienceRow).order_by(ExperienceRow.display_order.asc(), ExperienceRow.id.asc())
        if enabled_only:
            stmt = stmt.where(ExperienceRow.enabled.is_(True))
        rows = self._db.execute(stmt).scalars()
        return [experience_to_domain(r) for r in rows]

    def add(self, item: Experience) -> Experience:
        row = experience_to_row(item)
        self._db.add(row)
        self._db.flush()
        return experience_to_domain(row)

    def remove(self, id: str) -> None:
        row = self._db.get(ExperienceRow, id)
        if row is not None:
            self._db.delete(row)

    def upsert(self, item: Experience) -> Experience:
        row = self._db.get(ExperienceRow, item.id)
        new = experience_to_row(item)
        if row is None:
            self._db.add(new)
            self._db.flush()
            return experience_to_domain(new)
        # Copy all fields from the new row onto the existing row.
        for col in ExperienceRow.__table__.columns:
            setattr(row, col.name, getattr(new, col.name))
        self._db.flush()
        return experience_to_domain(row)