"""Experience service: catalog access.

Behavior:
- Reads first from the DB.
- If the DB has no rows, falls back to the in-memory seed so the kiosk
  can render before persistence is initialized (e.g., during cold boot).
- The first call that hits the seed seeds the DB, then continues to
  serve from the DB. Operator overrides in the DB take precedence.
"""

from __future__ import annotations

from sqlalchemy.orm import Session as OrmSession

from ..domain import Experience
from ..errors import NotFoundError
from ..repositories import ExperienceRepository
from .catalog_seed import SEED_EXPERIENCES


class ExperienceService:
    def __init__(self, db: OrmSession) -> None:
        self._db = db
        self._repo = ExperienceRepository(db)
        self._seeded = False

    def _ensure_seeded(self) -> None:
        """Lazily insert the in-memory seed into the DB on first access."""
        if self._seeded:
            return
        existing = self._repo.list(enabled_only=False)
        if not existing:
            for exp in SEED_EXPERIENCES:
                self._repo.upsert(exp)
        self._seeded = True

    def list(self, *, enabled_only: bool = True) -> list[Experience]:
        # Fast path (warm DB): single query, no seed check.
        rows = self._repo.list(enabled_only=enabled_only)
        if rows:
            return rows
        if self._seeded:
            # Already seeded yet still empty: serve in-memory fallback.
            return [e for e in SEED_EXPERIENCES if (not enabled_only or e.enabled)]
        # Cold DB: seed once, then re-query (3 queries once per process,
        # 1 query per call afterwards instead of 2 per call).
        self._ensure_seeded()
        rows = self._repo.list(enabled_only=enabled_only)
        if rows:
            return rows
        # Last-ditch fallback: in-memory seed.
        return [e for e in SEED_EXPERIENCES if (not enabled_only or e.enabled)]

    def get(self, experience_id: str) -> Experience:
        # Fast path: direct PK lookup first (1 query warm hit vs 2 before).
        exp = self._repo.get(experience_id)
        if exp is not None:
            return exp
        if not self._seeded:
            # Miss may mean cold DB: seed once, retry PK lookup.
            self._ensure_seeded()
            exp = self._repo.get(experience_id)
            if exp is not None:
                return exp
        # Last-ditch fallback for tests/legacy data.
        for e in SEED_EXPERIENCES:
            if e.id == experience_id:
                return e
        raise NotFoundError(f"Experience {experience_id} not found")

    def upsert(self, experience: Experience) -> Experience:
        self._ensure_seeded()
        return self._repo.upsert(experience)