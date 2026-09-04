# AURA Backend

FastAPI modular monolith for the AURA-Install project.

## Run (dev)
```bash
pip install -e ".[dev]"
cp ../../.env.example ../../.env  # then edit
python -m uvicorn aura_backend.main:app --reload --port 8000
```

## Layout
```
src/aura_backend/
  main.py              # FastAPI app, routes registration
  worker.py            # Background worker entrypoint (BullMQ-like loop)
  config.py            # Pydantic Settings
  logging.py           # Structured logging (structlog)
  errors.py            # Domain exception hierarchy
  events.py            # In-process event bus
  security.py          # JWT + device-token helpers
  db/
    __init__.py        # Engine + session factory
    models.py          # SQLAlchemy ORM models
  modules/
    health/            # /healthz, /readyz
    sessions/          # Visitor session FSM
    captures/          # Frame upload handling
    jobs/              # Job lifecycle + provider orchestration
    reel/              # Reel policy + playlist
    ws/                # WebSocket gateway
    provider_ai/       # Inference provider abstraction (RunPod / Fake)
    storage/           # Blob store abstraction (S3 / local FS)
```