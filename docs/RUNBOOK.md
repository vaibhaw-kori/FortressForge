# Operator runbook (prototype)

## Start the demo
1. `python -m uvicorn aura_backend.main:app --reload --port 8000` (backend)
2. `python -m aura_backend.worker` (job worker)
3. `npm run dev:kiosk` (Display 1)
4. `npm run dev:stage` (Display 2)
5. `npm run dev:console` (operator)

## Health checks
- `curl localhost:8000/healthz` → must return `{"status":"ok"}`
- `curl localhost:8000/readyz` → `db.ok` must be `true`

## Common failures
| Symptom | Likely cause | Fix |
|---|---|---|
| `/readyz` shows `db.ok=false` | DB path/perm | check `AURA_DATABASE_URL` + `./data/` perms |
| Frontend shows `backend: unreachable` | backend not running | start backend on :8000 |
| Job stuck in `PENDING` | worker not running | start worker |
| Job stuck in `SUBMITTED` | RunPod endpoint offline | check creds; fall back to `fake` |
| FFmpeg error in fake provider | FFmpeg not installed | install FFmpeg or change provider |

## Reset
- Stop all processes.
- `rm -rf data/` to wipe SQLite + local storage.
- Restart.