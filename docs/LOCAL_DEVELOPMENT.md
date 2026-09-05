# Local Development Mode — AURA-Install

No RunPod. No GPU. Full visitor flow runs locally.

## Architecture

```
Display 1 (kiosk :5173)
  ↓  POST /api/v1/sessions + capture + transition
Local FastAPI ( :8000, AURA_RUNPOD_PROVIDER_DEFAULT=mock )
  ↓  GenerationJobService → JobQueue
Local generation job (InMemoryQueue → InferenceWorker)
  ↓  MockVideoGenerationProvider.drive()
  QUEUED → PROCESSING → GENERATING → POST_PROCESSING → ENCODING → COMPLETED
  (configurable delay, progress_steps 0.1/0.3/0.6/0.9)
Local generated test video (curated-a.mp4 copied to storage/generated/{job_id}.mp4 )
  ↓  _ensure_generated_video_file (cached curated-sample, CWD-independent)
WebSocket event (job_completed → reel_new_video)
  ↓  realtime/relay → realtime/hub
Display 2 (stage :5174, ReelManager + VideoStage, 4 insert policies)
  ↓  GET /api/v1/storage/generated/...?expires=&signature= (signed URL, 200 video/mp4)
Reel playback (real MP4, ftyp mp42, 788493 bytes)
```

## Provider switch

Business logic never branches on the provider. Only config changes:

```env
# mock — deterministic, offline, real MP4 from local storage
AURA_RUNPOD_PROVIDER_DEFAULT=mock
AURA_MOCK_TOTAL_MS=1800   # simulated generation wall-clock

# runpod — later, real GPU (requires AURA_RUNPOD_API_KEY, no code change)
# AURA_RUNPOD_PROVIDER_DEFAULT=runpod
# AURA_RUNPOD_API_KEY=...

# wan-local — local Wan 2.1 on A6000 (requires AURA_WAN_PROVIDER_ENABLED=true)
# AURA_RUNPOD_PROVIDER_DEFAULT=wan-local
```

`main.py:37` always registers `MockVideoGenerationProvider` (`mock` + `fake` alias); `worker.py:358` drives it via `provider.drive()` with progress callbacks.

## Quick start

```bash
# 1. backend
cp .env.example .env   # .env already ships with AURA_RUNPOD_PROVIDER_DEFAULT=mock
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\Activate.ps1
pip install -e ./services/backend
python -m uvicorn aura_backend.main:app --host 127.0.0.1 --port 8000 --reload
# verify: curl http://127.0.0.1:8000/api/v1/health

# 2. frontends (pnpm workspace, CSP removed for dev, alias @aura/contracts → packages/contracts)
pnpm install
pnpm --filter=@aura/kiosk dev --host 127.0.0.1 --port 5173
pnpm --filter=@aura/stage dev --host 127.0.0.1 --port 5174
# open http://127.0.0.1:5173 (kiosk) + http://127.0.0.1:5174 (stage, F11)
```

## 16-step verification (automated)

`httpx` flow (0 → 2.0s COMPLETED, real MP4 served):

1. `POST /sessions {language}` → 201 LANGUAGE_SELECTED
2. `POST /sessions/{id}/transition {to: THEME_SELECTED, theme_id: aurora}` → 200
3. `POST /sessions/{id}/capture` (JPEG) → 200 key captures/{id}.jpg
4. `POST /generation/jobs {session_id, experience_id}` → 201 QUEUED
5. `GET /generation/jobs/{id}` poll → PROCESSING (0.0) → COMPLETED (1.0)
6. `output.key = generated/{prefix}/{job_id}.mp4`, `size_bytes=788493`, `codec=h264`
7. `GET /api/v1/storage/generated/...?expires=&signature=` → 200 video/mp4, ftyp mp42
8. WS `job_completed` → `reel_new_video` → Display 2 inserts without interrupting current
9. `RESET` → `LANGUAGE_SELECTION` for next visitor (state machine `kioskMachine.ts:196`)

## Tests

```bash
python -m pytest -q  # 437 passed
# torch-gating tests monkeypatch _TORCH_AVAILABLE=False so they pass with or without GPU
```
