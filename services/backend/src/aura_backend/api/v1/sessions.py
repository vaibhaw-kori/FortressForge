"""Session routes (API v1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session as OrmSession

from ...db import get_db
from ...security import require_kiosk_token, require_operator
from ...services import SessionService
from .schemas import (
    CreateSessionRequest,
    SessionResponse,
    SessionTransitionRequest,
)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _service(db: OrmSession = Depends(get_db)) -> SessionService:
    return SessionService(db)


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: CreateSessionRequest, svc: SessionService = Depends(_service)
) -> SessionResponse:
    # Validate language
    if body.language and body.language not in ("en", "ar"):
        from ...errors import ValidationFailed

        raise ValidationFailed("Unsupported language")
    s = svc.create(language=body.language)
    return SessionResponse.model_validate(s.__dict__)


@router.delete("/{session_id}", status_code=status.HTTP_200_OK)
async def delete_session(
    session_id: str,
    _auth=Depends(require_kiosk_token),
) -> dict:
    """Delete session and all associated captures/jobs/files. Requires kiosk token."""
    from ...services.retention import delete_session_cascade

    jobs_deleted, files_deleted = delete_session_cascade(session_id)
    return {"deleted": True, "jobs_deleted": jobs_deleted, "files_deleted": files_deleted}


@router.get("", response_model=list[SessionResponse])
async def list_sessions(svc: SessionService = Depends(_service)) -> list[SessionResponse]:
    return [SessionResponse.model_validate(s.__dict__) for s in svc.list()]


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str, svc: SessionService = Depends(_service)
) -> SessionResponse:
    s = svc.get(session_id)
    return SessionResponse.model_validate(s.__dict__)


@router.post("/{session_id}/transition", response_model=SessionResponse)
async def transition_session(
    session_id: str,
    body: SessionTransitionRequest,
    svc: SessionService = Depends(_service),
) -> SessionResponse:
    target = body.to
    if target.value == "LANGUAGE_SELECTED":
        if not body.language:
            from ...errors import ValidationFailed

            raise ValidationFailed("language required to transition to LANGUAGE_SELECTED")
        s = svc.select_language(session_id, body.language)
    elif target.value == "THEME_SELECTED":
        if not body.theme_id:
            from ...errors import ValidationFailed

            raise ValidationFailed("theme_id required to transition to THEME_SELECTED")
        s = svc.select_theme(session_id, body.theme_id)
    elif target.value == "COUNTDOWN":
        s = svc.start_countdown(session_id)
    elif target.value == "CAPTURING":
        s = svc.start_capture(session_id)
    elif target.value == "GENERATING":
        s = svc.mark_generating(session_id)
    elif target.value == "COMPLETED":
        s = svc.mark_completed(session_id)
    elif target.value == "ERROR":
        s = svc.mark_error(session_id)
    elif target.value == "IDLE":
        s = svc.reset(session_id)
    elif target.value == "UPLOADED":
        # Idempotent: if already UPLOADED, return current; else try FSM
        try:
            # Use existing capture_ref if set, else fallback key
            existing = svc.get(session_id)
            key = existing.capture_ref or f"captures/{session_id}.jpg"
            s = svc.mark_uploaded(session_id, key)
        except Exception:
            # If already in UPLOADED or GENERATING, just return current
            s = svc.get(session_id)
    else:
        from ...errors import ValidationFailed

        raise ValidationFailed(f"Unsupported transition target: {target.value}")
    return SessionResponse.model_validate(s.__dict__)