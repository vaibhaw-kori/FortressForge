# Architecture (Locked)

The full architecture proposal lives in the conversation history. This
file summarizes the **locked** state for day-to-day reference.

## One-line summary
Modular monolith FastAPI backend + three Vite/React frontends + RunPod
serverless inference + SQLite/Postgres + Redis-optional queue +
S3-compatible storage + native WebSockets.

## Components

| Component | Tech | Purpose |
|---|---|---|
| Backend API | FastAPI / Pydantic / SQLAlchemy | Modular monolith, stateless HTTP API |
| Backend Worker | asyncio loop | Polls jobs, drives providers |
| Provider registry | `VideoGenProvider` ABC | RunPod + Fake (+ self-hosted placeholder) |
| Storage | `BlobStore` ABC | Local FS prototype; S3 in prod |
| Sessions | FSM with `SessionState` | Visitor capture lifecycle |
| Jobs | FSM with `JobState` | Idempotent generation jobs |
| Reel | Pure policy function + in-memory queue | Configurable insert policy |
| WebSockets | `@fastapi/websocket` | `/ws/kiosk/{id}`, `/ws/stage`, `/ws/operator` |
| Kiosk (D1) | Vite/React/TS | Language + theme + capture UI |
| Stage (D2) | Vite/React/TS | Reel + visitor video playback |
| Operator | Vite/React/TS | Live status + policy view |

## Data flow (happy path)
1. Kiosk `POST /sessions` → session row
2. Kiosk `POST /sessions/{id}/capture` → frame stored, capture_ref set
3. Kiosk `POST /jobs` → job row, session → GENERATING, WS event
4. Worker submits to provider; polls until succeeded
5. Worker copies artifact to `aura-generated`, marks SUCCEEDED
6. WS event `job.completed` → stage inserts into reel per policy

## Deferred (architected for, not built)
- Kubernetes, Kafka, service mesh, GraphQL, WebRTC, multi-tenant orgs