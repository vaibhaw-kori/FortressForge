"""GenerationJob repository."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from ..db.mappers import job_from_domain, job_to_domain
from ..db.models import GenerationJobRow, JobStateDB
from ..domain import GenerationJob, GenerationJobState
from .base import Repository


class GenerationJobRepository(Repository[GenerationJob]):
    def __init__(self, db: OrmSession) -> None:
        self._db = db

    def get(self, id: str) -> GenerationJob | None:
        row = self._db.get(GenerationJobRow, id)
        return job_to_domain(row) if row else None

    def list(self) -> list[GenerationJob]:
        rows = self._db.execute(
            select(GenerationJobRow).order_by(GenerationJobRow.created_at.desc())
        ).scalars()
        return [job_to_domain(r) for r in rows]

    def list_by_session(self, session_id: str) -> list[GenerationJob]:
        rows = self._db.execute(
            select(GenerationJobRow)
            .where(GenerationJobRow.session_id == session_id)
            .order_by(GenerationJobRow.created_at.desc())
        ).scalars()
        return [job_to_domain(r) for r in rows]

    def list_by_state(self, state: GenerationJobState) -> list[GenerationJob]:
        rows = self._db.execute(
            select(GenerationJobRow)
            .where(GenerationJobRow.state == JobStateDB(state.value))
            .order_by(GenerationJobRow.created_at.asc())
        ).scalars()
        return [job_to_domain(r) for r in rows]

    def find_by_idempotency_key(self, key: str) -> GenerationJob | None:
        row = self._db.execute(
            select(GenerationJobRow).where(GenerationJobRow.idempotency_key == key)
        ).scalar_one_or_none()
        return job_to_domain(row) if row else None

    def add(self, item: GenerationJob) -> GenerationJob:
        row = GenerationJobRow(**job_from_domain(item))
        self._db.add(row)
        self._db.flush()
        return job_to_domain(row)

    def update(self, item: GenerationJob) -> GenerationJob:
        row = self._db.get(GenerationJobRow, item.id)
        if row is None:
            return self.add(item)
        data = job_from_domain(item)
        for k, v in data.items():
            if k in {"created_at", "id"}:
                continue
            setattr(row, k, v)
        self._db.flush()
        return job_to_domain(row)

    def remove(self, id: str) -> None:
        row = self._db.get(GenerationJobRow, id)
        if row is not None:
            self._db.delete(row)