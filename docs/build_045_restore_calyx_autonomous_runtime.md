# BUILD-045: Restore Calyx Autonomous Runtime

BUILD-045 fixes the runtime enablement path that left Calyx permanently disabled after deployment.

## Complete Disabled-State Trace

The deployed `main` path produced `runtime_engine_disabled` this way:

1. `AUTO_LOOP_ENABLED` was computed from `OC_RUNNER_AUTOLOOP`, defaulting to `false` when the variable was absent.
2. `RuntimeEngine(..., enabled=AUTO_LOOP_ENABLED)` created the engine with `enabled=false`.
3. FastAPI startup called `runtime_engine.start()` unconditionally.
4. `RuntimeEngine.start()` saw `enabled=false`, recorded `runtime_engine_disabled`, and returned `False`.
5. `POST /api/runner/autonomous-start` called `runtime_engine.start()` again without first enabling the engine.
6. The endpoint returned `already_running_or_disabled` while status remained `enabled=false`, `running=false`, and `thread_alive=false`.

## Conditions That Can Disable Runtime

After BUILD-045, Calyx autonomous runtime is enabled by default. It is disabled only by explicit configuration:

Explicit disable flags:

- `CALYX_AUTONOMOUS_DISABLED=true`
- `OC_RUNNER_DISABLED=true`
- `CALYX_RUNTIME_DISABLED=true`

Explicit enable flags set false:

- `OC_RUNNER_AUTOLOOP=false`
- `CALYX_RUNTIME_ENABLED=false`
- `AUTONOMOUS_RUNTIME_ENABLED=false`
- `RUNNER_ENABLED=false`
- `CALYX_AUTONOMOUS_ENABLED=false`

If none of these values explicitly disables the runtime, Calyx starts normally after deployment and `POST /api/runner/autonomous-start` can also enable/start it manually.

Inspected deployed `main` path notes:

- No persisted runtime state is read before constructing `RuntimeEngine`.
- No mission registry, policy registry, feature flag table, database value, or Constitution guardrail disables runtime startup in this code path.
- `DATABASE_URL` is required for queue work, but absence of `DATABASE_URL` is not used as a startup disabled flag. A cycle can fail and report `last_error`; it should not leave the engine permanently disabled.

## Runtime Behavior

- Startup calls `runtime_engine.set_enabled(True)` and `runtime_engine.start()` when no explicit blocker exists.
- Manual `POST /api/runner/autonomous-start` checks blockers, sets `enabled=true`, then starts the worker.
- Duplicate worker threads are still prevented by `RuntimeEngine.start()`.
- The autonomous loop uses `execute_next`, not `execute_all`, so one queued job is processed per cycle.
- `POST /api/runner/autonomous-stop` stops the worker and disables future starts by default. Use `?disable=false` to stop the worker without changing enabled state.

## Verify After Deployment

1. `GET /api/runner/autonomous-status`
2. `POST /api/runner/autonomous-start`
3. `GET /api/runner/autonomous-status`
4. `POST /api/runner/autonomous-cycle`
5. `GET /api/runner/summary`

Expected status after deployment/start when no explicit blocker exists:

```json
{
  "enabled": true,
  "running": true,
  "thread_alive": true,
  "config_blocker": null
}
```

`cycle_count` should increase after `POST /api/runner/autonomous-cycle`. If queue execution fails, inspect `last_error`; the runtime should remain enabled unless an explicit blocker exists.
