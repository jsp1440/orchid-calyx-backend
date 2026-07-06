# BUILD-044A: Calyx Autonomous Runtime State-Machine Fix

BUILD-044A repairs the manual autonomous runtime start path. The deployed bug was that `POST /api/runner/autonomous-start` called `runtime_engine.start()` while the runtime state still had `enabled=false`, so the engine correctly refused to start and returned `already_running_or_disabled`.

## What Changed

- Manual start now checks for explicit safety blockers first.
- If no blocker exists, manual start transitions `enabled=false` to `enabled=true` before starting the worker thread.
- Duplicate worker threads are still prevented by the runtime engine.
- `started_at`, `running`, `thread_alive`, and runtime events are updated by the engine.
- Autonomous startup on process boot remains opt-in through `OC_RUNNER_AUTOLOOP=true`.
- Autonomous cycles now execute one queued job per cycle through `execute_next`, not `execute_all`.
- Manual stop stops the worker and disables future auto-runs by default. Use `POST /api/runner/autonomous-stop?disable=false` to stop the thread without clearing `enabled`.

## Render Environment Variables

- `OC_RUNNER_AUTOLOOP=true` starts the autonomous runtime during FastAPI startup. Default is `false`.
- `OC_RUNNER_INTERVAL_SECONDS=30` controls cycle interval. Values below five seconds are raised by the runtime engine.
- `OC_RUNNER_ACTIVE_MODE=true` is reported in status for operator visibility.

Explicit safety disable flags:

- `CALYX_AUTONOMOUS_DISABLED=true`
- `OC_RUNNER_DISABLED=true`
- `CALYX_RUNTIME_DISABLED=true`

If any safety disable flag is truthy, `POST /api/runner/autonomous-start` returns `runtime_disabled_by_config` with the blocking key. Remove the variable or set it to `false` on Render to allow manual start.

## Verification

After deployment, test in this order:

1. `GET /api/runner/autonomous-status`
2. `POST /api/runner/autonomous-start`
3. `GET /api/runner/autonomous-status`
4. `POST /api/runner/autonomous-cycle`
5. `GET /api/runner/summary`

Expected manual start result when no safety disable flag is set:

```json
{
  "status": "started",
  "engine": {
    "enabled": true,
    "running": true,
    "thread_alive": true
  }
}
```

If the worker is already running, the endpoint returns `already_running` with the same engine state instead of creating a duplicate thread.
