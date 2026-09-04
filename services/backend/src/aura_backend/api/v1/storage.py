"""Storage serving (for local filesystem backend)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse

from ...storage import LocalStorage, get_storage, is_private_key, verify_signed_url

router = APIRouter(prefix="/storage", tags=["storage"])


@router.get("/{key:path}")
async def serve_storage_file(
    key: str,
    request: Request,
    expires: str | None = Query(default=None),
    signature: str | None = Query(default=None),
):
    """Serve a file from storage. Private objects require valid signed URL."""
    # Validate key early to prevent traversal
    from ...storage import sanitize_key

    try:
        sanitized = sanitize_key(key)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid key")

    # Private objects require signed URL validation
    if is_private_key(sanitized):
        if not expires or not signature:
            raise HTTPException(status_code=403, detail="Signed URL required")
        if not verify_signed_url(sanitized, expires, signature):
            raise HTTPException(status_code=403, detail="Invalid or expired signature")

    storage = get_storage()
    if isinstance(storage, LocalStorage):
        path = Path(storage.base_path) / sanitized
        # Double-check path is within base
        try:
            path.resolve().relative_to(Path(storage.base_path).resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Path traversal blocked")
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        suffix = path.suffix.lower()
        media_type = (
            "video/mp4"
            if suffix == ".mp4"
            else "image/jpeg"
            if suffix in (".jpg", ".jpeg")
            else "application/octet-stream"
        )
        # Private: no-cache; public: cacheable
        headers = {"Cache-Control": "private, max-age=3600"} if is_private_key(sanitized) else {"Cache-Control": "public, max-age=31536000"}
        return FileResponse(str(path), media_type=media_type, headers=headers)
    else:
        # For S3, redirect to presigned URL (already signed by storage layer)
        try:
            # Re-use the signed URL logic for S3 as well
            if is_private_key(sanitized) and not verify_signed_url(sanitized, expires or "", signature or ""):
                raise HTTPException(status_code=403, detail="Invalid signature")
            url = storage.get_url(sanitized)
            return RedirectResponse(url, status_code=302)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=404, detail="File not found")
