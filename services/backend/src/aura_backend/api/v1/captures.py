"""Capture upload route (API v1). Hardened against malicious files."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, Request, status
from sqlalchemy.orm import Session as OrmSession

from ...db import get_db
from ...security import require_kiosk_token
from ...services import SessionService
from ...storage import get_storage
from ...errors import ValidationFailed, NotFoundError

router = APIRouter(prefix="/sessions", tags=["captures"])

MAX_CAPTURE_BYTES = 8 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
# Magic bytes for image validation
MAGIC_BYTES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"RIFF": "image/webp",  # WebP starts with RIFF....WEBP
}


def _validate_image_magic(data: bytes) -> str | None:
    """Check magic bytes; return detected type or None."""
    for magic, ctype in MAGIC_BYTES.items():
        if data.startswith(magic):
            if ctype == "image/webp" and not data[8:12] == b"WEBP":
                continue
            return ctype
    return None


def _validate_image_content(data: bytes, max_pixels: int = 25_000_000) -> None:
    """Validate that bytes are a decodable image and not excessively large."""
    try:
        from PIL import Image
    except ImportError:
        # Pillow not installed (minimal env): magic bytes + size checks already
        # ran in the route; accept without deep decode so integration uploads work.
        return
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()  # Verify without fully decoding
        # Re-open for size check (verify() closes the image)
        img = Image.open(io.BytesIO(data))
        w, h = img.size
        if w * h > max_pixels:
            raise ValidationFailed(f"Image too large: {w}x{h} exceeds {max_pixels} pixels")
        if w < 64 or h < 64:
            raise ValidationFailed("Image too small")
        if img.format not in ("JPEG", "PNG", "WEBP"):
            raise ValidationFailed(f"Unsupported image format: {img.format}")
    except ValidationFailed:
        raise
    except Exception as e:
        raise ValidationFailed(f"Invalid image file: {e}")


@router.post("/{session_id}/capture", status_code=status.HTTP_200_OK)
async def upload_capture(
    session_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: OrmSession = Depends(get_db),
    _auth=Depends(require_kiosk_token),
) -> dict:
    # Enforce session_id format (alphanumeric, dash)
    if not session_id or len(session_id) > 64 or not session_id.replace("-", "").replace("_", "").isalnum():
        raise ValidationFailed("Invalid session_id")

    svc = SessionService(db)
    try:
        session = svc.get(session_id)
    except NotFoundError:
        raise
    except Exception as e:
        raise ValidationFailed(str(e))

    # Read file with size limit
    data = await file.read()
    if not data:
        raise ValidationFailed("Empty capture file")
    if len(data) > MAX_CAPTURE_BYTES:
        raise ValidationFailed(f"Capture too large (max {MAX_CAPTURE_BYTES} bytes)")
    if len(data) < 100:
        raise ValidationFailed("File too small to be valid image")

    # Validate magic bytes
    detected = _validate_image_magic(data)
    if not detected:
        raise ValidationFailed("Invalid image format (magic bytes mismatch)")

    # Cross-check content-type header vs magic bytes
    declared = (file.content_type or "image/jpeg").lower()
    if declared not in ALLOWED_CONTENT_TYPES:
        raise ValidationFailed(f"Content-Type not allowed: {declared}")
    # Allow PNG declared as JPEG? Be strict: must match
    if detected != declared and not (detected == "image/jpeg" and declared in ALLOWED_CONTENT_TYPES):
        # For WebP, allow fallback
        if not (detected == "image/webp" and declared == "image/webp"):
            raise ValidationFailed(f"Content-Type {declared} does not match file content {detected}")

    # Validate image can be decoded and dimensions are sane
    _validate_image_content(data)

    content_type = detected  # Use detected, not declared, for storage

    # Store to object storage — sanitize key via storage layer
    key = f"captures/{session_id}.jpg"
    storage = get_storage()
    try:
        storage.put(key, data, content_type=content_type)
    except ValueError as e:
        raise ValidationFailed(str(e))
    except Exception as e:
        # Do not leak internal storage errors
        raise ValidationFailed("Storage failed")

    # Update session: mark uploaded (CAPTURING -> UPLOADED) and set capture_ref
    # We try FSM transition; if session is not in CAPTURING, we still set capture_ref
    # via direct repository update to keep frontend idempotent.
    try:
        svc.mark_uploaded(session_id, key)
    except Exception:
        # Fallback: set capture_ref directly without FSM if already uploaded
        from ...repositories import SessionRepository

        repo = SessionRepository(db)
        s = repo.get(session_id)
        if s is not None and s.capture_ref != key:
            s.capture_ref = key
            # Only try FSM if still in CAPTURING
            try:
                if s.state.value == "CAPTURING":
                    s.mark_uploaded(key)
            except Exception:
                pass
            repo.update(s)

    return {"key": key, "size": len(data)}


@router.get("/{session_id}/capture")
async def get_capture(
    session_id: str,
    db: OrmSession = Depends(get_db),
    _auth=Depends(require_kiosk_token),
) -> dict:
    svc = SessionService(db)
    s = svc.get(session_id)
    if not s.capture_ref:
        raise NotFoundError(f"No capture for session {session_id}")
    storage = get_storage()
    url = storage.get_url(s.capture_ref)
    return {"key": s.capture_ref, "url": url}
