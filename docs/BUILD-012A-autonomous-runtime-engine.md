# BUILD-012A — Autonomous Runtime Engine

BUILD-012A gives Calyx a persistent runtime loop instead of requiring a human to manually call `/api/runner/execute-next`.

## What changed

- Added `runtime/runtime_engine.py`.
- Wired a singleton `RuntimeEngine` into FastAPI startup and shutdown.
- Added runtime engine lifecycle/status endpoints:
  - `GET /api/runner/autonomous-status`
  - `POST /api/runner/autonomous-cycle`
  - `POST /api/runner/autonomous-start`
  - `POST /api/runner/autonomous-stop`
- Extended `/api/runner/summary` to include runtime engine state.
- Added runtime action logging for completed and failed queue jobs.
- Adjusted queue selection to ignore invalid legacy records where `job_name` is null.

## Runtime cycle

Each autonomous cycle runs:

1. `CalyxHeartbeat().run_once()`
2. `run_once()` to enqueue core optimization jobs idempotently
3. `execute_all()` to drain currently pending valid jobs
4. Update in-memory runtime engine status
5. Sleep for `OC_RUNNER_INTERVAL_SECONDS`

## Environment variables

- `OC_RUNNER_AUTOLOOP=true` enables the background engine on service startup.
- `OC_RUNNER_INTERVAL_SECONDS=30` controls cycle interval. Values below 5 seconds are clamped to 5 seconds.
- `DATABASE_URL` is still required for database-backed queue operations.

## Acceptance check after deploy

1. Set `OC_RUNNER_AUTOLOOP=true` in Render.
2. Deploy the backend.
3. Open `/api/runner/autonomous-status` and confirm:
   - `enabled: true`
   - `running: true`
   - `cycle_count` increases over time
4. Open `/api/runner/summary` and confirm recent pending jobs are completed without manually pressing Execute Next.

## Notes

This build does not add new research agents or email ingestion. It establishes the always-on runtime foundation those services can plug into later.
