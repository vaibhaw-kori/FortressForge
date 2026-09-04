# Security notes (prototype)

## Boundaries
- Frontends never see RunPod keys. The backend is the only process with
  inference credentials.
- Frontends call backend via `/api/*` and `/ws/*` proxies; no direct
  egress to RunPod.

## Auth (prototype defaults)
- Kiosks: opaque device token via `AURA_KIOSK_TOKEN_DEFAULT`.
- Operator: JWT (HS256) issued at `/ops/login` (placeholder).

## CORS / CSP
- CORS allowlist via `AURA_CORS_ALLOW_ORIGINS`.
- Frontend CSP (TODO in build pipeline) restricts `connect-src` and
  `media-src` to backend origin.

## Data
- Captures and generated videos stored in private buckets with signed
  URLs in production.
- Session data minimized; explicit consent + retention required before
  UAE PDPL exposure.

## Production hardening checklist
- [ ] TLS termination at edge
- [ ] Rotate `AURA_OPERATOR_JWT_SECRET` and kiosk tokens
- [ ] Move secrets to a vault (AWS Secrets Manager / Doppler)
- [ ] Add rate limiting (`fastapi-limiter`)
- [ ] CSP headers on frontends
- [ ] Audit log table for operator actions
- [ ] Pen-test + dependency scan in CI