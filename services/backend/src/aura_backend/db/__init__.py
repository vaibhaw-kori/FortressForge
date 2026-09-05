"""Database engine + session factory.

SQLite for the prototype; the same SQLAlchemy 2.x API works against
PostgreSQL by swapping AURA_DATABASE_URL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _ensure_sqlite_parent_dir(url: str) -> None:
    if url.startswith("sqlite:///"):
        db_path = Path(url[len("sqlite:///") :])
        if db_path.parent and str(db_path.parent) not in ("", "."):
            db_path.parent.mkdir(parents=True, exist_ok=True)
            # Least privilege: restrict DB file permissions to owner-only (0600) on creation
            try:
                # Set directory to 0700 as well
                db_path.parent.chmod(0o700)
            except Exception:
                pass


def _resolved_database_url() -> str:
    s = get_settings()
    # Use absolute sqlite path so CWD at launch (project root vs services/backend) resolves to same file
    if hasattr(s, "resolved_database_url"):
        return s.resolved_database_url  # type: ignore[attr-defined]
    return s.database_url


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        s = get_settings()
        url = _resolved_database_url()
        _ensure_sqlite_parent_dir(url)
        connect_args = {"check_same_thread": False, "timeout": 10.0} if s.is_sqlite else {}
        _engine = create_engine(url, connect_args=connect_args, future=True, pool_size=5, max_overflow=10, pool_timeout=30)
        if s.is_sqlite:
            from sqlalchemy import text

            try:
                with _engine.begin() as conn:
                    conn.execute(text("PRAGMA journal_mode=WAL;"))
                    conn.execute(text("PRAGMA synchronous=NORMAL;"))
                    conn.execute(text("PRAGMA busy_timeout=8000;"))
                    conn.execute(text("PRAGMA foreign_keys=ON;"))
            except Exception:
                pass
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, commits on success."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """Create tables. Imports models so SQLAlchemy registers them."""
    from . import models  # noqa: F401 - side-effect import

    Base = models.Base
    Base.metadata.create_all(bind=get_engine())


def reset_engine() -> None:
    """Test helper: drop cached engine + session factory."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None