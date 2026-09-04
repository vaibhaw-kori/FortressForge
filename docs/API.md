# REST API (prototype)

All paths are relative to the backend base URL. Frontends use the Vite
proxy at `/api/*` which strips the prefix.

## Health
- `GET /healthz` — liveness
- `GET /readyz` — readiness (checks DB)

## Sessions
- `POST /sessions` `{language?}` → `{id, state}`
- `GET /sessions/{id}` → `{id, state}`
- `POST /sessions/{id}/transition` `{to, language?, theme_id?, capture_ref?}` → `{id, state}`

## Captures
- `POST /sessions/{id}/capture` (multipart file) → `{key, size}`

## Jobs
- `POST /jobs` `{session_id, theme_id, provider_id?}` → `{id, ..., state}`
- `GET /jobs/{id}` → `{id, ..., state}`

## Reel
- `GET /reel/queue` → `[{id, kind, src, duration_sec, created_at}]`
- `POST /reel/insert` `{item}` → `{accept, reason, queue_len}`
- `GET /reel/policy` → `{policy}`

## Storage (prototype only)
- `PUT /storage/local-put?key=...` (body bytes) → `{key, status}`

## WebSockets
- `/ws/kiosk/{kiosk_id}?token=...`
- `/ws/stage`
- `/ws/operator`