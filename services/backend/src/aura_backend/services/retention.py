"""Retention and deletion service (defense-in-depth: minimize data lifetime)."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Tuple

from sqlalchemy import select

from ..config import get_settings
from ..db.models import GenerationJobRow, SessionRow
from ..logging import get_logger
from ..storage import get_storage

log = get_logger("aura.retention")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def purge_expired(delete_files: bool = True) -> dict[str, int]:
    """Delete expired captures and generated videos per retention policy.

    Returns counts of purged rows/files.
    This is idempotent and safe to run periodically.
    """
    from ..db import session_scope

    s = get_settings()
    now = _utcnow()
    cap_cutoff = now - timedelta(days=s.retention_captures_days)
    gen_cutoff = now - timedelta(days=s.retention_generated_days)

    purged_sessions = 0
    purged_jobs = 0
    deleted_files = 0

    storage = get_storage()

    with session_scope() as db:
        # Find expired sessions (by created_at)
        expired_sessions = db.execute(
            select(SessionRow).where(SessionRow.created_at < cap_cutoff)
        ).scalars().all()

        for sess in expired_sessions:
            # Delete associated capture file if present
            if delete_files and sess.capture_ref:
                try:
                    storage.delete(sess.capture_ref)
                    deleted_files += 1
                except Exception:
                    pass
            db.delete(sess)
            purged_sessions += 1

        # Find expired jobs (by created_at) — delete output files
        expired_jobs = db.execute(
            select(GenerationJobRow).where(GenerationJobRow.created_at < gen_cutoff)
        ).scalars().all()

        for job in expired_jobs:
            if delete_files and job.output_key:
                try:
                    storage.delete(job.output_key)
                    deleted_files += 1
                except Exception:
                    pass
            db.delete(job)
            purged_jobs += 1

    log.info("retention_purge", purged_sessions=purged_sessions, purged_jobs=purged_jobs, deleted_files=deleted_files)
    return {"purged_sessions": purged_sessions, "purged_jobs": purged_jobs, "deleted_files": deleted_files}


def delete_session_cascade(session_id: str, delete_files: bool = True) -> Tuple[int, int]:
    """Delete a single session and its associated jobs/files. Returns (jobs_deleted, files_deleted)."""
    from ..db import session_scope
    from sqlalchemy import delete as sa_delete

    storage = get_storage()
    jobs_deleted = 0
    files_deleted = 0

    with session_scope() as db:
        sess = db.get(SessionRow, session_id)
        if sess is None:
            return (0, 0)

        # Find jobs for this session
        jobs = db.execute(select(GenerationJobRow).where(GenerationJobRow.session_id == session_id)).scalars().all()
        for job in jobs:
            if delete_files and job.output_key:
                try:
                    storage.delete(job.output_key)
                    files_deleted += 1
                except Exception:
                    pass
            db.delete(job)
            jobs_deleted += 1

        if sess.capture_ref and delete_files:
            try:
                storage.delete(sess.capture_ref)
                files_deleted += 1
            except Exception:
                pass

        db.delete(sess)

    log.info("session_deleted", session_id=session_id, jobs_deleted=jobs_deleted, files_deleted=files_deleted)
    return (jobs_deleted, files_deleted)
