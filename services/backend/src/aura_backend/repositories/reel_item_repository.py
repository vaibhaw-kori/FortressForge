"""ReelItem repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..db.mappers import reel_item_from_domain, reel_item_to_domain
from ..db.models import ReelItemRow
from ..domain import ReelItem
from .base import Repository


class ReelItemRepository(Repository[ReelItem]):
    def __init__(self, db: OrmSession) -> None:
        self._db = db

    def get(self, id: str) -> ReelItem | None:
        row = self._db.get(ReelItemRow, id)
        return reel_item_to_domain(row) if row else None

    def list(self) -> list[ReelItem]:
        rows = self._db.execute(
            select(ReelItemRow).order_by(ReelItemRow.created_at.asc())
        ).scalars()
        return [reel_item_to_domain(r) for r in rows]

    def add(self, item: ReelItem) -> ReelItem:
        row = ReelItemRow(**reel_item_from_domain(item))
        self._db.add(row)
        self._db.flush()
        return reel_item_to_domain(row)

    def remove(self, id: str) -> None:
        row = self._db.get(ReelItemRow, id)
        if row is not None:
            self._db.delete(row)