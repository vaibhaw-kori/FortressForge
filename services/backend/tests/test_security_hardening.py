"""Security hardening tests: kiosk tokens, operator JWT, signed URLs, capture validation, headers/CORS/rate-limit."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials

from aura_backend.config import get_settings, reset_settings_cache
from aura_backend.errors import ForbiddenError, UnauthorizedError
from aura_backend.security import (
    check_kiosk_token,
    decode_operator_jwt,
    make_operator_jwt,
    require_kiosk_token,
    require_operator,
)


# ---------------------------------------------------------------------------
# kiosk token
# ---------------------------------------------------------------------------


class TestKioskToken:
    def test_check_valid(self, settings):
        assert check_kiosk_token(settings.kiosk_token_default) is True

    def test_check_invalid(self):
        assert check_kiosk_token("wrong-token") is False

    def test_check_missing(self):
        assert check_kiosk_token(None) is False
        assert check_kiosk_token("") is False

    def test_require_valid_header(self, settings):
        # Direct dependency call with valid header token.
        require_kiosk_token(
            x_kiosk_token=settings.kiosk_token_default, token_qs=None, authorization=None
        )

    def test_require_valid_query(self, settings):
        require_kiosk_token(
            x_kiosk_token=None, token_qs=settings.kiosk_token_default, authorization=None
        )

    def test_require_valid_bearer(self, settings):
        require_kiosk_token(
            x_kiosk_token=None,
            token_qs=None,
            authorization=f"Bearer {settings.kiosk_token_default}",
        )

    def test_require_invalid_raises(self):
        with pytest.raises(UnauthorizedError):
            require_kiosk_token(x_kiosk_token="bad", token_qs=None, authorization=None)

    def test_require_missing_allowed_in_dev(self, settings, monkeypatch):
        # conftest sets AURA_ENV=test → non-prod allows missing token.
        assert settings.env != "prod"
        require_kiosk_token(x_kiosk_token=None, token_qs=None, authorization=None)

    def test_require_missing_rejected_in_prod(self, monkeypatch):
        monkeypatch.setenv("AURA_ENV", "prod")
        reset_settings_cache()
        try:
            s = get_settings()
            assert s.env == "prod"
            with pytest.raises(UnauthorizedError):
                require_kiosk_token(x_kiosk_token=None, token_qs=None, authorization=None)
            # Even in prod, a valid token still passes.
            require_kiosk_token(
                x_kiosk_token=s.kiosk_token_default, token_qs=None, authorization=None
            )
            with pytest.raises(UnauthorizedError):
                require_kiosk_token(x_kiosk_token="wrong", token_qs=None, authorization=None)
        finally:
            monkeypatch.setenv("AURA_ENV", "test")
            reset_settings_cache()

    def test_kiosk_token_timing_safe(self, settings):
        # Same-length wrong token must still be rejected (constant-time compare).
        wrong = "x" * len(settings.kiosk_token_default)
        assert check_kiosk_token(wrong) is False


# ---------------------------------------------------------------------------
# operator JWT
# ---------------------------------------------------------------------------


class TestOperatorJWT:
    def test_roundtrip(self):
        token = make_operator_jwt("op-1")
        payload = decode_operator_jwt(token)
        assert payload["sub"] == "op-1"
        assert payload["scope"] == "operator"
        assert payload["exp"] > payload["iat"]

    def test_roundtrip_with_extra(self):
        token = make_operator_jwt("op-2", extra={"kiosk": "k1"})
        payload = decode_operator_jwt(token)
        assert payload["kiosk"] == "k1"
        assert payload["sub"] == "op-2"

    def test_expired_rejected(self, settings):
        now = int(time.time())
        expired = jwt.encode(
            {"sub": "op-1", "iat": now - 1000, "exp": now - 10, "scope": "operator"},
            settings.operator_jwt_secret,
            algorithm="HS256",
        )
        with pytest.raises(UnauthorizedError):
            decode_operator_jwt(expired)

    def test_wrong_secret_rejected(self):
        token = jwt.encode(
            {"sub": "op-1", "iat": int(time.time()), "exp": int(time.time()) + 900, "scope": "operator"},
            "completely-wrong-secret",
            algorithm="HS256",
        )
        with pytest.raises(UnauthorizedError):
            decode_operator_jwt(token)

    def test_malformed_rejected(self):
        with pytest.raises(UnauthorizedError):
            decode_operator_jwt("not.a.jwt")

    def test_wrong_scope_forbidden(self):
        token = make_operator_jwt("op-1", extra={"scope": "viewer"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        with pytest.raises(ForbiddenError):
            require_operator(creds, None)

    def test_require_operator_valid(self):
        token = make_operator_jwt("op-9")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        payload = require_operator(creds, None)
        assert payload["sub"] == "op-9"

    def test_require_operator_via_query(self):
        token = make_operator_jwt("op-q")
        payload = require_operator(None, token)
        assert payload["sub"] == "op-q"

    def test_require_operator_missing_raises(self):
        with pytest.raises(UnauthorizedError):
            require_operator(None, None)


# ---------------------------------------------------------------------------
# storage signed URLs
# ---------------------------------------------------------------------------


class TestSignedURLs:
    def test_create_verify_roundtrip(self):
        from aura_backend.storage import create_signed_url, verify_signed_url

        url = create_signed_url("captures/abc123.jpg")
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        assert "expires" in qs and "signature" in qs
        assert verify_signed_url("captures/abc123.jpg", qs["expires"][0], qs["signature"][0]) is True

    def test_expired_rejected(self):
        from aura_backend.storage import create_signed_url, verify_signed_url

        url = create_signed_url("captures/abc123.jpg", ttl_sec=-10)
        qs = parse_qs(urlparse(url).query)
        assert verify_signed_url("captures/abc123.jpg", qs["expires"][0], qs["signature"][0]) is False

    def test_tampered_signature_rejected(self):
        from aura_backend.storage import create_signed_url, verify_signed_url

        url = create_signed_url("captures/abc123.jpg")
        qs = parse_qs(urlparse(url).query)
        sig = qs["signature"][0]
        tampered = ("0" if sig[-1] != "0" else "1") + sig[1:]
        if tampered == sig:
            tampered = sig[:-1] + ("a" if sig[-1] != "a" else "b")
        assert verify_signed_url("captures/abc123.jpg", qs["expires"][0], tampered) is False

    def test_tampered_key_rejected(self):
        from aura_backend.storage import create_signed_url, verify_signed_url

        url = create_signed_url("captures/abc123.jpg")
        qs = parse_qs(urlparse(url).query)
        assert (
            verify_signed_url("captures/other.jpg", qs["expires"][0], qs["signature"][0]) is False
        )

    def test_tampered_expiry_rejected(self):
        from aura_backend.storage import create_signed_url, verify_signed_url

        url = create_signed_url("captures/abc123.jpg")
        qs = parse_qs(urlparse(url).query)
        future = str(int(qs["expires"][0]) + 99999)
        assert verify_signed_url("captures/abc123.jpg", future, qs["signature"][0]) is False

    def test_verify_malformed_returns_false(self):
        from aura_backend.storage import verify_signed_url

        assert verify_signed_url("captures/a.jpg", "notanint", "badsig") is False
        assert verify_signed_url("captures/a.jpg", "", "") is False

    @pytest.mark.parametrize(
        "bad_key",
        [
            "../etc/passwd",
            "captures/../../etc/passwd",
            "/absolute/path.jpg",
            "captures//evil.jpg",
            "captures/\x00evil.jpg",
            "captures/evil?.jpg",
            "captures/evil pic.jpg",
            "captures\\evil.jpg",
            "",
            "a" * 513,
        ],
    )
    def test_path_traversal_keys_rejected(self, bad_key):
        from aura_backend.storage import create_signed_url, sanitize_key

        with pytest.raises(ValueError):
            sanitize_key(bad_key)
        with pytest.raises(ValueError):
            create_signed_url(bad_key)

    def test_illegal_chars_rejected(self):
        from aura_backend.storage import sanitize_key

        for bad in ["captures/a;b.jpg", "captures/a|b.jpg", "captures/<a>.jpg", "captures/a$b.jpg"]:
            with pytest.raises(ValueError):
                sanitize_key(bad)

    def test_valid_keys_accepted(self):
        from aura_backend.storage import sanitize_key

        for good in [
            "captures/abc123.jpg",
            "generated/ab/abcdef.mp4",
            "thumbnails/a-b_c.d.jpg",
            "captures/x.jpg",
        ]:
            assert sanitize_key(good) == good

    def test_is_private_key(self):
        from aura_backend.storage import is_private_key

        assert is_private_key("captures/a.jpg") is True
        assert is_private_key("generated/a.mp4") is True
        assert is_private_key("thumbnails/a.jpg") is False
        assert is_private_key("public/a.jpg") is False


# ---------------------------------------------------------------------------
# capture upload validation (API level)
# ---------------------------------------------------------------------------


def _drive_to_capturing(db_session):
    from aura_backend.services import SessionService

    svc = SessionService(db_session)
    s = svc.create(language="en")
    svc.select_theme(s.id, "aurora")
    svc.start_countdown(s.id)
    svc.start_capture(s.id)
    db_session.commit()
    return s


JPEG_HEAD = b"\xff\xd8\xff\xe0\x00\x10JFIF"


class TestCaptureUpload:
    def test_empty_file_rejected(self, client, db_session):
        s = _drive_to_capturing(db_session)
        r = client.post(
            f"/api/v1/sessions/{s.id}/capture",
            files={"file": ("c.jpg", b"", "image/jpeg")},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_failed"

    def test_too_small_rejected(self, client, db_session):
        s = _drive_to_capturing(db_session)
        r = client.post(
            f"/api/v1/sessions/{s.id}/capture",
            files={"file": ("c.jpg", JPEG_HEAD + b"\x00" * 10, "image/jpeg")},
        )
        assert r.status_code == 422
        assert "too small" in r.json()["error"]["message"].lower()

    def test_too_large_rejected(self, client, db_session):
        from aura_backend.api.v1 import captures as cap_mod

        s = _drive_to_capturing(db_session)
        big = JPEG_HEAD + b"\x00" * (cap_mod.MAX_CAPTURE_BYTES + 1)
        r = client.post(
            f"/api/v1/sessions/{s.id}/capture",
            files={"file": ("c.jpg", big, "image/jpeg")},
        )
        assert r.status_code == 422
        assert "too large" in r.json()["error"]["message"].lower()

    def test_bad_magic_rejected(self, client, db_session):
        s = _drive_to_capturing(db_session)
        r = client.post(
            f"/api/v1/sessions/{s.id}/capture",
            files={"file": ("c.jpg", b"NOTANIMAGE" * 30, "image/jpeg")},
        )
        assert r.status_code == 422
        assert "magic" in r.json()["error"]["message"].lower()

    def test_wrong_content_type_rejected(self, client, db_session):
        s = _drive_to_capturing(db_session)
        data = JPEG_HEAD + b"\x00" * 500
        r = client.post(
            f"/api/v1/sessions/{s.id}/capture",
            files={"file": ("c.jpg", data, "text/plain")},
        )
        assert r.status_code == 422

    def test_content_mismatch_rejected(self, client, db_session):
        s = _drive_to_capturing(db_session)
        # PNG magic declared as JPEG → mismatch must be rejected.
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500
        r = client.post(
            f"/api/v1/sessions/{s.id}/capture",
            files={"file": ("c.png", png, "image/jpeg")},
        )
        assert r.status_code == 422

    @pytest.mark.parametrize("bad_sid", ["bad id!", "../evil", "a" * 65, "x;y", "a/b"])
    def test_invalid_session_id_format(self, client, bad_sid):
        data = JPEG_HEAD + b"\x00" * 500
        r = client.post(
            f"/api/v1/sessions/{bad_sid}/capture",
            files={"file": ("c.jpg", data, "image/jpeg")},
        )
        # Router may 404 on slash-containing paths; format violations must be 4xx, never 5xx/2xx.
        assert r.status_code in (404, 422)

    def test_invalid_session_id_format_no_slash(self, client):
        data = JPEG_HEAD + b"\x00" * 500
        r = client.post(
            "/api/v1/sessions/bad!id/capture",
            files={"file": ("c.jpg", data, "image/jpeg")},
        )
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_failed"

    def test_missing_session_404(self, client):
        data = JPEG_HEAD + b"\x00" * 500
        r = client.post(
            "/api/v1/sessions/doesnotexist123/capture",
            files={"file": ("c.jpg", data, "image/jpeg")},
        )
        assert r.status_code == 404

    def test_storage_put_valueerror_maps_to_422(self, client, db_session, monkeypatch):
        import aura_backend.api.v1.captures as cap_mod

        s = _drive_to_capturing(db_session)
        monkeypatch.setattr(cap_mod, "_validate_image_content", lambda data: None)

        class _BadStorage:
            def put(self, key, data, content_type="application/octet-stream"):
                raise ValueError("bad key detail")

            def get_url(self, key):
                return f"/x/{key}"

        import aura_backend.storage as storage_mod

        monkeypatch.setattr(storage_mod, "_storage", _BadStorage())
        # captures imports get_storage directly; patch the reference too.
        monkeypatch.setattr(cap_mod, "get_storage", lambda: storage_mod.get_storage())

        data = JPEG_HEAD + b"\x00" * 500
        r = client.post(
            f"/api/v1/sessions/{s.id}/capture",
            files={"file": ("c.jpg", data, "image/jpeg")},
        )
        assert r.status_code == 422
        body = r.json()
        assert body["error"]["code"] == "validation_failed"
        assert "bad key detail" in body["error"]["message"]

    def test_storage_put_generic_does_not_leak(self, client, db_session, monkeypatch):
        import aura_backend.api.v1.captures as cap_mod

        s = _drive_to_capturing(db_session)
        monkeypatch.setattr(cap_mod, "_validate_image_content", lambda data: None)

        class _ExplodingStorage:
            def put(self, key, data, content_type="application/octet-stream"):
                raise RuntimeError("SECRET: disk s3://internal exploded")

            def get_url(self, key):
                return f"/x/{key}"

        import aura_backend.storage as storage_mod

        monkeypatch.setattr(storage_mod, "_storage", _ExplodingStorage())
        monkeypatch.setattr(cap_mod, "get_storage", lambda: storage_mod.get_storage())

        data = JPEG_HEAD + b"\x00" * 500
        r = client.post(
            f"/api/v1/sessions/{s.id}/capture",
            files={"file": ("c.jpg", data, "image/jpeg")},
        )
        assert r.status_code == 422
        body = r.json()
        assert body["error"]["code"] == "validation_failed"
        assert "SECRET" not in body["error"]["message"]
        assert body["error"]["message"] == "Storage failed"

    def test_validate_magic_helper(self):
        from aura_backend.api.v1.captures import _validate_image_magic

        assert _validate_image_magic(JPEG_HEAD + b"\x00" * 200) == "image/jpeg"
        assert _validate_image_magic(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200) == "image/png"
        assert _validate_image_magic(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 200) == "image/webp"
        assert _validate_image_magic(b"NOPE" + b"\x00" * 200) is None


# ---------------------------------------------------------------------------
# headers / CORS / rate limiting
# ---------------------------------------------------------------------------


class TestHeadersCorsRateLimit:
    def test_security_headers_present(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "camera=" in r.headers.get("Permissions-Policy", "")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp

    def test_security_headers_on_api_errors(self, client):
        r = client.get("/api/v1/sessions/missing-id-xyz")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_cors_middleware_installed(self, app):
        from starlette.middleware.cors import CORSMiddleware

        kinds = [m.cls for m in app.user_middleware]
        assert CORSMiddleware in kinds

    def test_rate_limit_headers_present(self, client):
        from aura_backend.middleware.rate_limit import get_limiter

        get_limiter().reset()
        r = client.get("/api/v1/experiences")
        assert r.status_code == 200
        assert "X-RateLimit-Limit" in r.headers
        assert int(r.headers["X-RateLimit-Limit"]) > 0

    def test_rate_limiter_unit(self):
        from aura_backend.middleware.rate_limit import InMemoryRateLimiter

        lim = InMemoryRateLimiter(requests_per_minute=2, burst=1)
        assert lim.is_allowed("k") is True
        assert lim.is_allowed("k") is True
        assert lim.is_allowed("k") is True
        assert lim.is_allowed("k") is False
        # Different key unaffected.
        assert lim.is_allowed("other") is True
        lim.reset()
        assert lim.is_allowed("k") is True

    def test_rate_limit_429_smoke(self, client):
        from aura_backend.middleware import rate_limit as rl_mod

        limiter = rl_mod.get_limiter()
        limiter.reset()
        old_rpm, old_burst = limiter.rpm, limiter.burst
        limiter.rpm = 2
        limiter.burst = 0
        try:
            got_429 = False
            for _ in range(10):
                r = client.get("/api/v1/experiences")
                if r.status_code == 429:
                    got_429 = True
                    assert r.json()["error"]["code"] == "rate_limited"
                    assert r.headers.get("Retry-After") == "60"
                    break
            assert got_429, "expected 429 after exceeding tiny limit"
        finally:
            limiter.rpm, limiter.burst = old_rpm, old_burst
            limiter.reset()

    def test_health_skips_rate_limit(self, client):
        from aura_backend.middleware.rate_limit import get_limiter

        lim = get_limiter()
        lim.reset()
        old_rpm, old_burst = lim.rpm, lim.burst
        lim.rpm = 1
        lim.burst = 0
        try:
            # Exhaust the limiter for this IP.
            for _ in range(5):
                client.get("/api/v1/experiences")
            # Health must still succeed (skipped by middleware).
            r = client.get("/api/v1/health")
            assert r.status_code == 200
        finally:
            lim.rpm, lim.burst = old_rpm, old_burst
            lim.reset()
