"""Health/readiness routes (API v1).

Public, unauthenticated. Intentionally minimal: no DB schema details,
no version strings in the URL, no secrets leaked via headers.
"""

from __future__ import annotations

import platform
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from ... import __version__
from ...db import get_engine
from ...logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger("aura.health")


@router.get("/health")
async def health() -> dict[str, Any]:
    """Liveness probe."""
    return {
        "status": "ok",
        "service": "aura-backend",
        "version": __version__,
        "python": platform.python_version(),
    }


@router.get("/ready")
async def ready() -> dict[str, Any]:
    """Readiness probe: verifies DB engine can execute SELECT 1."""
    db_ok = True
    db_error: str | None = None
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_error = str(exc)
        log.warning("ready_db_failed", error=db_error)

    return {
        "status": "ok" if db_ok else "degraded",
        "db": {"ok": db_ok, "error": db_error},
        "runtime": {"python": platform.python_version()},
    }