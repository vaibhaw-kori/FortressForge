"""Simple in-memory rate limiter (prototype).

Not distributed; resets on restart. For production, replace with Redis.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ..config import get_settings
from ..logging import get_logger

log = get_logger("aura.rate_limit")


class InMemoryRateLimiter:
    def __init__(self, requests_per_minute: int = 60, burst: int = 20):
        self.rpm = requests_per_minute
        self.burst = burst
        # client_key -> deque of timestamps
        self._buckets: dict[str, Deque[float]] = defaultdict(deque)
        self._window = 60.0

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        bucket = self._buckets[key]
        # Remove expired
        while bucket and bucket[0] < now - self._window:
            bucket.popleft()
        # Allow burst + rpm
        limit = self.rpm + self.burst
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True

    def reset(self):
        self._buckets.clear()


_limiter: InMemoryRateLimiter | None = None


def get_limiter() -> InMemoryRateLimiter:
    global _limiter
    if _limiter is None:
        s = get_settings()
        _limiter = InMemoryRateLimiter(
            requests_per_minute=s.rate_limit_requests_per_minute,
            burst=s.rate_limit_burst,
        )
    return _limiter


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip health/readiness and storage GET (signed URL already rate-limited by expiry)
        if request.url.path in ("/api/v1/health", "/api/v1/ready", "/docs", "/openapi.json"):
            return await call_next(request)

        # Skip WS
        if request.url.path.startswith("/ws"):
            return await call_next(request)

        # Key by IP + session if available
        client_ip = request.client.host if request.client else "unknown"
        # Prefer token if present to prevent IP spoofing bypass
        token = request.headers.get("x-kiosk-token") or request.query_params.get("token") or ""
        key = f"{client_ip}:{token[:8]}" if token else client_ip

        limiter = get_limiter()
        if not limiter.is_allowed(key):
            log.warning("rate_limited", client_ip=client_ip, path=request.url.path)
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "rate_limited", "message": "Too many requests", "details": {}}},
                headers={"Retry-After": "60"},
            )
        response = await call_next(request)
        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(limiter.rpm + limiter.burst)
        return response
