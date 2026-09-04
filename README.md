# AURA-Install

Premium AI-powered interactive installation — Dubai client prototype.

Two displays (kiosk + stage), RunPod GPU inference, modular monolith
backend, real-time WebSocket fan-out, S3-compatible storage.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the locked design.

## Repository Layout
```
apps/
  kiosk/              # Display 1 (Vite + React + TS)
  stage/              # Display 2 (Vite + React + TS)
  operator-console/   # Admin UI
packages/
  contracts/          # Shared DTOs / event types
  reel/               # Client-side reel primitives
  frontend-base/      # Shared TS config
inference/            # AI provider abstraction (Python)
services/
  backend/            # FastAPI modular monolith + worker
docs/                 # Architecture + API + WS + security + runbook
```

## Quick start (prototype)

### 1. Backend
```bash
cd services/backend
pip install -e ".[dev]"
cd ../..
python -m uvicorn aura_backend.main:app --reload --port 8000
```
Health: http://localhost:8000/healthz

### 2. Worker (separate process)
```bash
python -m aura_backend.worker
```

### 3. Frontends (separate terminals)
```bash
npm install
npm run dev:kiosk    # http://localhost:5173
npm run dev:stage    # http://localhost:5174
npm run dev:console  # http://localhost:5175
```
Each frontend proxies `/api` and `/ws` to the backend.

### 4. Tests
```bash
cd services/backend && pytest
npm run test:frontend
```

## Environment
Copy `.env.example` to `.env` and fill in values. Never commit `.env`.

For the prototype, the default `fake` provider runs the entire pipeline
without GPUs or RunPod credentials.

## Production path
- Swap `AURA_DATABASE_URL` to Postgres
- Swap `AURA_REDIS_URL` on and run BullMQ workers
- Provide `AURA_RUNPOD_ENDPOINT_*` and `AURA_RUNPOD_API_KEY`
- Move storage to AWS S3 + CloudFront
- Add TLS, WAF, observability (OpenTelemetry → Grafana/Tempo)
- Lock retention policy and consent UI per UAE PDPL