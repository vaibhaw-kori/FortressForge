"""Admin/operator endpoints. All require operator JWT."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ...security import require_operator
from ...services.retention import purge_expired

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/purge", dependencies=[Depends(require_operator)])
async def purge_retention() -> dict:
    """Trigger retention purge. Operator only."""
    result = purge_expired(delete_files=True)
    return result


@router.get("/retention", dependencies=[Depends(require_operator)])
async def get_retention_policy() -> dict:
    from ...config import get_settings

    s = get_settings()
    return {
        "retention_captures_days": s.retention_captures_days,
        "retention_generated_days": s.retention_generated_days,
        "storage_signed_url_ttl_sec": s.storage_signed_url_ttl_sec,
    }


@router.post("/storage/cleanup-temp", dependencies=[Depends(require_operator)])
async def cleanup_temp() -> dict:
    """Clean up temporary files from inference pipeline."""
    import tempfile
    import pathlib

    tmpdir = pathlib.Path(tempfile.gettempdir()) / "aura_generated"
    deleted = 0
    if tmpdir.exists():
        for f in tmpdir.glob("*.mp4"):
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass
        for f in tmpdir.glob("*.jpg"):
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass
    return {"deleted_temp_files": deleted}
