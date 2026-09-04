# AURA-Install Security Model

**Version:** 0.1.0  
**Date:** 2026-09-02  
**Status:** Defense-in-depth, not absolute guarantee  
**Threat model:** High-profile Dubai installation, public kiosk, large-screen stage, laptop demo → RunPod GPU, no WebRTC.

This document describes what is protected, how, and what remains risky. **No system can claim mathematically proven security.** We instead apply multiple independent layers so a single failure does not lead to data leakage.

---

## 1. Secrets Management

* **Env-only, never committed.** `config.py:18` loads `AURA_*` from `../../.env` / `.env`. `.gitignore:24` ignores `.env`, `data/`, `*.db`. `.env.example` contains only `AURA_RUNPOD_API_KEY=` (empty) and insecure defaults for dev.
* **Fail-fast in prod.** `config.py:96` `validate_secrets()` refuses to start if `operator_jwt_secret`, `storage_signing_secret`, or `kiosk_token_default` are still `change-me-*` when `AURA_ENV=prod`. In dev it only warns (`main.py:110`).
* **No hard-coded prod secrets** anywhere in `apps/*` or `services/backend/src`.
* **Rotation:** Change `AURA_OPERATOR_JWT_SECRET`, `AURA_STORAGE_SIGNING_SECRET`, `AURA_KIOSK_TOKEN_DEFAULT`, `AURA_RUNPOD_API_KEY` via deployment secrets manager (Doppler/AWS SM) and restart; old signed URLs expire within 1h (`storage_signing_secret`).

## 2. RunPod Credentials

* Stored only in backend env (`AURA_RUNPOD_API_KEY`, `AURA_RUNPOD_ENDPOINT_*` `config.py:50`), never in any `apps/*` bundle. Vite proxy (`apps/kiosk/vite.config.ts:8`, `apps/stage/vite.config.ts:8`) forwards only `/api`/`/ws` to backend; frontend never contacts `*.runpod.net`.
* **Never logged:** `logging.py:12` `REDACT_KEYS` + regex redacts `api_key`, `token`, `secret`, `authorization` in every structlog event; large blobs (>500 chars) truncated. `inference/runpod_provider.py` surfaces `ProviderAuthError` without echoing the key.
* **Least privilege:** RunPod endpoint uses a single serverless endpoint per model, scoped API key with only `run/infer` permission (create a per-installation key in RunPod dashboard, not your account master key).

## 3. API Authentication & Authorization

* **Kiosk (Display 1):** `security.py:36` `require_kiosk_token` — checks `X-Kiosk-Token` header or `?token=` or `Authorization: Bearer` via `hmac.compare_digest`. In `prod` missing/invalid → 401. Applied to `POST /sessions/{id}/capture` `captures.py:32`, `POST /generation/jobs` `generation.py:72`, `GET /generation/jobs/{id}` etc., `DELETE /sessions/{id}`, `GET /sessions/{id}/capture`. In `dev` missing token is allowed for ease of `TestClient`.
* **Operator:** `security.py:45` `require_operator` — validates `Authorization: Bearer <JWT>` (HS256, `operator_jwt_secret`, 900s TTL) and `scope==operator`. Applied to `POST /api/v1/admin/purge` and `/retention` `admin.py:10`.
* **Separation:** Kiosk token cannot purge, operator JWT cannot be used as kiosk token (different header/validation path).

## 4. Input Validation

* Pydantic strict on all `api/v1/schemas.py` (field `max_length`, `ge/le`), `sessions.py:24` checks `language in ("en","ar")`, `session_id` alphanumeric, `captures.py:18` validates `session_id` format.
* `domain/` FSMs (`SessionState`, `GenerationJobState`) reject illegal transitions as 409, not 500.
* `storage/sanitize_key` `storage/__init__.py:18` rejects `..`, `//`, absolute, non-alphanum keys.

## 5. File Upload Validation

* `captures.py:18` `MAX_CAPTURE_BYTES=8MiB`, `MAGIC_BYTES` check (JPEG `FF D8 FF`, PNG `89 50 4E 47`, WebP `RIFF....WEBP`), `PIL.Image.verify()` + size check (<64px or >25M pixels rejected), content-type must match magic bytes. Rejects empty/too-small files.

## 6. Path Traversal

* Every storage operation calls `sanitize_key` and `Path.resolve().relative_to(base)` (`storage/__init__.py:51`). Direct `storage.get_url` never returns a filesystem path. `api/v1/storage.py:18` re-validates key and blocks `..`.

## 7. Malicious File Handling

* Image is re-opened via PIL, not executed. No `eval`/`pickle`. Video encoding uses `cv2.VideoWriter` with fixed codec `mp4v`, no user-controlled command line. Provider input is JSON only.

## 8. Temporary File Cleanup

* `inference/wan_pipeline.py:528` stores temp at `tempfile.gettempdir()/aura_generated/{job_id}.mp4`, then `storage.put` → signed URL, then `unlink(missing_ok=True)` even on error. `inference/worker.py:320` also deletes temp path after `storage.put`. `admin.py:15` `POST /admin/storage/cleanup-temp` and `purge_expired` remove leftovers. No raw visitor bytes kept in logs.

## 9. Object Storage Access

* **Private by default:** `storage/__init__.py:18` `PRIVATE_PREFIXES=("captures/","generated/")` require signed URLs. `LocalStorage` and `S3Storage` both enforce.
* **Signed URLs:** `create_signed_url` `storage/__init__.py:32` HMAC-SHA256(`key:expires`, `storage_signing_secret`), 1h TTL (`config.py:64`). `verify_signed_url` checks expiry + `hmac.compare_digest`. `api/v1/storage.py:18` returns 403 if missing/invalid/expired. Public thumbnails bypass signing but still validate key.
* **No listing:** No `GET /storage` list endpoint.

## 10. WebSocket Authentication

* `realtime/routes.py:54` `require_token` must equal `kiosk_token_default` (constant-time compare). Missing/invalid → `close(4401)` before `accept`. Operator WS uses same token (and can be upgraded to JWT). Idle >60s → `close(4408)` via `hub.py:120` sweeper. `ping` every 15s, `pong` required.

## 11. CORS

* `main.py:116` `CORSMiddleware` allow-list from `AURA_CORS_ALLOW_ORIGINS` (`config.py:87` defaults to `http://localhost:5173,5174,5175`), methods limited to `GET,POST,PUT,DELETE,OPTIONS`, headers `Authorization,Content-Type,X-Kiosk-Token`, `max_age=600`. `allow_credentials=True` only with explicit origins (never `*`).

## 12. Rate Limiting

* `middleware/rate_limit.py:18` `InMemoryRateLimiter` 60 req/min + burst 20 per IP+token. `RateLimitMiddleware` skips health/docs/WS, returns `429` + `Retry-After:60` + `X-RateLimit-Limit`. In prod replace with Redis.

## 13. Logging

* `logging.py:11` structlog + `REDACT_KEYS` processor redacts `token, api_key, secret, capture_ref` etc., truncates blobs >500 chars, masks `data:image` URLs. JSON to stdout, never to file by default.

## 14. Sensitive Data Leakage in Logs

* **Never logged:** `API keys`, `tokens`, `passwords`, raw `captures/*.jpg` bytes, raw `generated/*.mp4` bytes. Verified by grep for `capture_ref` in `logging.py` redaction and manual review of `captures.py` (no `log.info(data)`).

## 15. Error Messages

* `errors.py:134` all handlers return `{error:{code,message,details:{}}}` with generic `Internal server error` for unhandled; no stack trace to client. `log.exception` stays server-side. 422 for validation, 401/403 for auth, 409 for FSM, 429 for rate limit, 502 for provider/storage (no internal details).

## 16. Dependency Security

* `services/backend/pyproject.toml` pins `fastapi`, `pydantic`, `httpx`, `sqlalchemy` with `>=` lower bounds; `apps/*/package.json` pins React 18. CI should run `pip audit` and `npm audit` (see Runbook). No `eval`, no `pickle`, no `shell=True` in inference (only `ffmpeg` via `subprocess.run` with fixed args).

## 17. Frontend Exposure

* Frontend bundles contain **no** `AURA_RUNPOD_*`, `AURA_STORAGE_*`, `AURA_OPERATOR_JWT_SECRET`. Vite `define` not used for secrets; only `VITE_USE_MOCKS` (non-secret). CSP in `apps/kiosk/index.html:6` and `apps/stage/index.html:6`: `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; media-src 'self' blob: http://localhost:8000 http://localhost:9000; connect-src 'self' ws://localhost:8000 wss://localhost:8000; frame-ancestors 'none'`. `middleware/security_headers.py:10` adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Permissions-Policy: camera=(self)`, `Strict-Transport-Security` on https.

## 18. Network Exposure

* `config.py:33` `backend_host` defaults `0.0.0.0` for RunPod VPC but **docs recommend** `127.0.0.1` behind Caddy/Nginx with TLS termination in prod. `docs/RUNBOOK.md` covers `mkcert` locally, Cloudflare/WAF in prod. No `0.0.0.0` in frontend; Vite dev binds `127.0.0.1` via `--host 127.0.0.1`.

## 19. Least Privilege

* DB file `data/aura.db` dir `0700`, file `0600` (`db/__init__.py:18`). Storage base `data/storage` `0700`. No `chmod 777`. App runs as non-root in Dockerfile (when used). Only `GET /health`/`/ready` are unauthenticated.

## 20. Retention / Deletion

* `config.py:64` `retention_captures_days=7`, `retention_generated_days=30`. `services/retention.py:18` `purge_expired()` deletes expired `SessionRow`+`GenerationJobRow` and their storage files (idempotent). `DELETE /api/v1/sessions/{id}` `sessions.py:32` cascades to jobs+capture+generated files (kiosk token required). `POST /api/v1/admin/purge` (operator JWT) triggers manual purge. No backup retention beyond policy.

## 21. Generated Media Access

* Private by default: `GET /api/v1/storage/generated/...` requires `?expires=&signature=` signed URL (`storage.py:18` 403 otherwise). `GenerationJobService` returns `output.url` already signed (`storage.get_url` `storage/__init__.py:71`). `GET /api/v1/generation/jobs/{id}` requires kiosk token, so an attacker guessing `job_id` still needs token. No binary via WS (`realtime/relay.py` sends only `src` URL, not bytes). `GET /sessions/{id}/capture` also requires kiosk token and returns signed URL.

## 22. Remaining Risks (not fixed, acknowledged)

* **In-memory rate limiter** resets on restart and is per-process; a distributed flood across replicas is not mitigated — replace with Redis in prod.
* **Signed URL secret** is symmetric (`storage_signing_secret`); if leaked, all private URLs can be forged until rotated. Rotate via env and restart.
* **Local storage** (`data/storage`) is filesystem, not encrypted at rest; use S3 with SSE-S3/KMS in prod.
* **PIL verify** is not a full malware scan; a crafted JPEG could still exploit a future libjpeg vuln — keep `pillow` patched via `pip audit`.
* **No WAF** in prototype; add Cloudflare/AWS WAF in prod for L7 filtering.
* **No per-tenant isolation**; single-tenant prototype. Multi-mall would need org-scoped keys.
* **No audit log** beyond structured logs; operator actions (`DELETE`, `purge`) are logged but not in a tamper-evident store.

---

### Quick start (secure)

```bash
cp .env.example .env
# Edit .env: set AURA_OPERATOR_JWT_SECRET, AURA_STORAGE_SIGNING_SECRET, AURA_KIOSK_TOKEN_DEFAULT (32+ random chars)
# For RunPod:
#   AURA_RUNPOD_API_KEY=...
#   AURA_RUNPOD_ENDPOINT=...
#   AURA_RUNPOD_PROVIDER_DEFAULT=runpod-svd
# Prod:
#   AURA_ENV=prod
#   AURA_CORS_ALLOW_ORIGINS=https://kiosk.yourdomain.com,https://stage.yourdomain.com
python -m uvicorn aura_backend.main:app --host 127.0.0.1 --port 8000
# Storage and generated videos are private; access via signed URLs only.
```

### Verification

* `pytest` — 207+ tests including `test_wan_pipeline`, `test_realtime`, `test_async_job_system`
* `grep -R "runpod_api_key" apps/` — must be empty
* `grep -R "data:image" services/backend/src --include="*.py" | grep log` — must be redacted
* `curl /api/v1/storage/captures/...` without `?expires=&signature=` → 403
* `curl -H "X-Kiosk-Token: wrong" POST /api/v1/sessions/.../capture` → 401
