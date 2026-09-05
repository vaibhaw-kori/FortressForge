"""Security helpers: device tokens + operator JWT + FastAPI dependencies."""

from __future__ import annotations

import time
from typing import Any

import jwt
from fastapi import Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import get_settings
from .errors import ForbiddenError, UnauthorizedError

security_bearer = HTTPBearer(auto_error=False)


def make_operator_jwt(subject: str, extra: dict[str, Any] | None = None) -> str:
    s = get_settings()
    now = int(time.time())
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + s.operator_jwt_ttl_sec,
        "scope": "operator",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, s.operator_jwt_secret, algorithm="HS256")


def decode_operator_jwt(token: str) -> dict[str, Any]:
    s = get_settings()
    try:
        return jwt.decode(token, s.operator_jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc


def check_kiosk_token(token: str | None) -> bool:
    s = get_settings()
    if not token:
        return False
    # Constant-time compare to avoid timing attacks
    import hmac

    return hmac.compare_digest(token, s.kiosk_token_default)


def require_kiosk_token(
    x_kiosk_token: str | None = Header(default=None),
    token_qs: str | None = Query(default=None, alias="token"),
    authorization: str | None = Header(default=None),
) -> None:
    """Dependency for kiosk-facing endpoints. Allows header or query param."""
    s = get_settings()
    # Tests use env=test with no token; allow anon ONLY there. Dev still
    # requires the kiosk token (frontend always sends X-Kiosk-Token), so a
    # misconfigured AURA_ENV=dev in production cannot silently open kiosk APIs.
    if s.env == "test" and not x_kiosk_token and not token_qs and not authorization:
        return
    token = x_kiosk_token or token_qs
    # Also allow Authorization: Bearer <kiosk_token>
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
    if not check_kiosk_token(token):
        raise UnauthorizedError("Invalid kiosk token")


def require_operator(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_bearer),
    token_qs: str | None = Query(default=None, alias="token"),
) -> dict[str, Any]:
    """Dependency for operator endpoints. Requires valid JWT."""
    s = get_settings()
    # Allow query param for WS
    token = None
    if credentials and credentials.credentials:
        token = credentials.credentials
    elif token_qs:
        token = token_qs
    if not token:
        raise UnauthorizedError("Missing operator token")
    payload = decode_operator_jwt(token)
    if payload.get("scope") != "operator":
        raise ForbiddenError("Insufficient scope")
    return payload


def optional_operator(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_bearer),
    token_qs: str | None = Query(default=None, alias="token"),
) -> dict[str, Any] | None:
    """Optional operator auth — returns None if not present."""
    try:
        return require_operator(credentials, token_qs)
    except (UnauthorizedError, ForbiddenError):
        return None