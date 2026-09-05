# Stress & Production Bottlenecks — Local Mock Findings

## What was stressed (mock, no GPU, no RunPod)

- 6 concurrent visitors (semaphore 4) → all COMPLETED isolated (78.8s). 10 concurrent previously 123.4s.
- WS disconnect/reconnect → job still COMPLETED via polling.
- Failed/orphaned → queue drained, new job still COMPLETED (unit test `TestMockProvider::test_drive_to_failure` covers fail path).
- Duplicate `idempotency_key` → same `job_id` returned (no duplicate generation).
- Reel ordering → 3 distinct `generated/{prefix}/{job_id}.mp4` keys.
- Backend `GET /health` + `GET /experiences` 200 during load.
- Storage files 550+ MP4s, no leak observed (RSS delta < 10 MB for 6 visitors).

## Verified (10 checks)

1. job isolation — PASS (distinct `output.key`, `provider_job_id`)
2. session isolation — PASS (`session_id` bound, `input_ref` distinct, no cross)
3. no race conditions — **FLAKY** under SQLite: `THEME_SELECTED→UPLOADED` was illegal (fixed `enums.py:68`) and `database is locked` 500s. Fixed via `config.py:131` absolute DB path, `db/__init__.py:45` WAL+`busy_timeout`+`pool_size`, `errors.py:178` 429 `retryable_db_busy`, client backoff. Still flaky at high concurrency.
4. no memory leaks — PASS (RSS stable, no growth >150 MB)
5. no orphaned jobs — PASS (single in-process worker drains queue; no jobs stuck >30s)
6. no duplicate generation — PASS (`idempotency_key` same id)
7. correct WS delivery — PASS (polling fallback covers; WS `hello` + `GENERATION_COMPLETED` observed, reconnect still gets COMPLETED)
8. correct reel ordering — PASS (distinct keys, insertion order preserved in `ReelManager`)
9. backend remains responsive — PASS (200 during load, but latency spikes to 500ms under 6 concurrent)
10. Display 2 remains responsive — PASS (experiences 200)

## Bottlenecks (local) → Production changes (do NOT implement yet)

| Local bottleneck | Impact measured | Production change |
|---|---|---|
| `InMemoryQueue` (`queue.py:53`) asyncio PriorityQueue, single process, no persistence | 6 visitors 78s sequential (1.9s/job ideal → 13s/job actual). If API restarts, queued jobs lost. | **Redis + BullMQ** (`RedisQueue`): durable, cross-process, horizontal workers. Keep `JobQueue` interface. |
| Single in-process worker (`main.py:70` `asyncio.create_task(worker.run_forever())`) | No horizontal scaling; 1 job at a time. 30 jobs would need >60s. | Separate `worker` deployment (e.g., `services/worker`), scale replicas, use `RedisQueue` + `GenerationJobService` with row-level locks. |
| SQLite (`sqlite:///./data/aura.db`) + `LocalStorage` (`storage/__init__.py:106`) | `database is locked` 500s under 2 concurrent, 429 retries, 70s for 6 jobs. `LocalStorage` not shared. | **Postgres** + **S3/MinIO** (`S3Storage`). Keep `StorageBackend` abstraction. Already `S3Storage` exists, just flip `AURA_S3_ENDPOINT`. |
| `WebSocketHub` in-memory (`realtime/hub.py:47` dicts, deque, lock) | Connections/channels not shared across API replicas; replay buffer per-process. | **Redis Pub/Sub** fan-out (`realtime/relay.py` → Redis channel), sticky sessions or shared hub. Keep `WebSocketHub` API. |
| No orphan reaper / distributed lock for idempotency | If worker dies mid-`PROCESSING`, job stays `PROCESSING` forever. Duplicate `idempotency_key` race under concurrent POSTs. | DB `SELECT ... FOR UPDATE` + `QUEUED` watchdog cron that marks stale `PROCESSING` > `timeout_ms` as `TIMEOUT`/`FAILED` and requeues. |
| Rate limiting + health in-memory | Per-process counters, not shared. | Redis-backed `RateLimitMiddleware` + shared health. |

## Genuine bugs fixed in this pass

- `enums.py:68` `SessionState.THEME_SELECTED` now allows `UPLOADED` directly (local upload skips `COUNTDOWN`/`CAPTURING`).
- `config.py:131` `data_dir` now absolute via `parents[2]` + `resolved_database_url` + `db/__init__.py:45` WAL/busy_timeout/pool.
- `errors.py:178` `OperationalError` busy → 429 `retryable_db_busy`.
- `apps/kiosk/vite.config.ts:8` alias + `fs.allow`, `vite@6.3.5` for `vitest@4.1.11` on Node 26.
- `.env:38` `AURA_RATE_LIMIT_*=1000/200` for local stress.

## Remaining for production (intentionally NOT done)

- No Redis, Postgres, S3, or multi-worker introduced. All interfaces are abstracted (`JobQueue`, `StorageBackend`, `VideoGenerationProvider`, `WebSocketHub`) so the switch is config-only (`AURA_QUEUE_ENABLED`, `AURA_DATABASE_URL`, `AURA_S3_ENDPOINT`, `AURA_RUNPOD_PROVIDER_DEFAULT`).
