# WebSocket protocol

Channels:
- `/ws/kiosk/{kioskId}?token=<device-token>`
- `/ws/stage`
- `/ws/operator`

Auth: kiosks use device tokens; stage + operator are open in the
prototype (lock down in production).

Events pushed by server (see `packages/contracts/src/index.ts` for TS
mirrors):

| Event | Where | Payload |
|---|---|---|
| `hello` | all | `{type, channel}` |
| `job.created` | operator | `{job_id, session_id, theme_id}` |
| `job.completed` | operator, stage | `{job_id, session_id, output_ref, duration_sec}` |
| `job.failed` | operator | `{job_id, reason?}` |
| `job.dead` | operator | `{job_id}` |

Clients send heartbeat / control text frames (currently unused; the
server reads and discards to detect disconnects).

Reconnect strategy: on reconnect, client calls `GET /sessions/{id}` to
reconcile state before resuming the event stream.