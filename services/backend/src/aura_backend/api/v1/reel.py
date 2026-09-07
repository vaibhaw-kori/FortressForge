"""Reel playlist for Display 2. Scans durable storage for generated mp4s."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from ...storage import get_storage

router = APIRouter(prefix="/reel", tags=["reel"])
# Also mounted at /api/reel for the stage's legacy path (see main.py)
legacy_router = APIRouter(prefix="/reel", tags=["reel"])

def _list_generated(limit: int = 20) -> list[dict]:
    storage = get_storage()
    # LocalStorage is file-backed: scan data/storage/generated
    from ...config import get_settings
    base = Path(get_settings().data_dir) / "storage" / "generated"
    items: list[dict] = []
    if base.exists():
        for p in sorted(base.rglob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
            # key is relative to storage base, e.g. generated/d1/xxxx.mp4
            try:
                rel = p.relative_to(Path(get_settings().data_dir) / "storage")
                key = rel.as_posix()
            except Exception:
                key = f"generated/{p.name}"
            # signed URL so Display2 can actually play it
            url = storage.get_url(key)
            items.append({
                "id": p.stem,
                "kind": "generated",
                "src": url,
                "title": "Generated",
                "duration_sec": 4,
            })
    return items


@router.get("/queue")
async def get_reel_queue() -> list[dict]:
    return _list_generated()

@legacy_router.get("/queue")
async def get_reel_queue_legacy() -> list[dict]:
    return _list_generated()
