"""Domain error hierarchy + FastAPI exception handlers.

All errors raised by services flow through this module so the API
emits a consistent JSON envelope.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .domain.enums import JobTransitionError, SessionTransitionError
from .logging import get_logger

log = get_logger("aura.errors")


class AuraError(Exception):
    """Base domain error.

    Accepts either:
    - AuraError("message")
    - AuraError("message", details={...})
    - AuraError("code", "message")  (legacy/provider-friendly form)
    """

    status_code: int = 500
    code: str = "internal_error"

    def __init__(
        self,
        message_or_code: str = "",
        message_or_details: str | dict | None = None,
        *,
        details: dict | None = None,
    ) -> None:
        # Three-arg form: AuraError("code", "message", details=...) is not
        # supported because of the legacy two-arg form below. We instead
        # detect legacy (code, message) vs new (message) by type of arg2.
        if isinstance(message_or_details, dict):
            msg = message_or_code
            details = message_or_details
            code = self.code
        elif isinstance(message_or_details, str):
            code = message_or_code
            msg = message_or_details
        else:
            msg = message_or_code
            details = details
            code = self.code
        super().__init__(msg or code)
        self.code = code
        self.message = msg or code
        self.details = details or {}


class NotFoundError(AuraError):
    status_code = 404
    code = "not_found"


class ValidationFailed(AuraError):
    status_code = 422
    code = "validation_failed"


class UnauthorizedError(AuraError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AuraError):
    status_code = 403
    code = "forbidden"


class ConflictError(AuraError):
    status_code = 409
    code = "conflict"


class IllegalTransitionError(AuraError):
    """Illegal FSM transition surfaced as HTTP 409."""

    status_code = 409
    code = "illegal_transition"


class JobNotFoundError(NotFoundError):
    code = "job_not_found"


class JobAlreadyTerminalError(ConflictError):
    """Job is in a terminal state and cannot accept the requested action."""

    code = "job_already_terminal"


class JobIdempotencyConflict(ConflictError):
    """Idempotency key was reused with a different payload."""

    code = "job_idempotency_conflict"


class ProviderError(AuraError):
    status_code = 502
    code = "provider_error"


class ProviderTimeoutError(ProviderError):
    code = "provider_timeout"


class ProviderAuthError(ProviderError):
    status_code = 502
    code = "provider_auth_error"
    """The provider rejected our credentials. Operator must rotate keys."""


class ProviderRateLimitedError(ProviderError):
    code = "provider_rate_limited"
    """Provider asked us to back off. Worker should retry with delay."""


class StorageError(AuraError):
    status_code = 502
    code = "storage_error"


def _payload(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(IllegalTransitionError)
    async def _illegal(_: Request, exc: IllegalTransitionError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(SessionTransitionError)
    async def _session_tx(_: Request, exc: SessionTransitionError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_payload(
                "illegal_transition",
                str(exc),
                {"from": exc.frm, "to": exc.to, "scope": "session"},
            ),
        )

    @app.exception_handler(JobTransitionError)
    async def _job_tx(_: Request, exc: JobTransitionError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_payload(
                "illegal_transition",
                str(exc),
                {"from": exc.frm, "to": exc.to, "scope": "job"},
            ),
        )

    @app.exception_handler(AuraError)
    async def _aura_error_handler(_: Request, exc: AuraError) -> JSONResponse:
        log.warning("aura_error", code=exc.code, message=exc.message)
        return JSONResponse(
            status_code=exc.status_code, content=_payload(exc.code, exc.message, exc.details)
        )

    @app.exception_handler(ValueError)
    async def _value_error(_: Request, exc: ValueError) -> JSONResponse:
        log.info("value_error", error=str(exc))
        return JSONResponse(
            status_code=422, content=_payload("validation_failed", str(exc))
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Retryable SQLite busy/locked -> 429 so the local stress client can backoff and retry
        # (production uses Postgres, so this is prototype-only).
        try:
            from sqlalchemy.exc import OperationalError

            if isinstance(exc, OperationalError):
                msg = str(exc).lower()
                if "locked" in msg or "busy" in msg or "database is locked" in msg:
                    log.warning("retryable_db_busy", error=str(exc)[:300])
                    return JSONResponse(
                        status_code=429,
                        content=_payload("retryable_db_busy", "Database busy, retry"),
                        headers={"Retry-After": "1"},
                    )
        except Exception:
            pass
        log.exception("unhandled_error", error=str(exc))
        return JSONResponse(
            status_code=500, content=_payload("internal_error", "Internal server error")
        )