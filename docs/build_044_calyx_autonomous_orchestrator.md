# BUILD-044: Calyx Autonomous Runtime + Mission Planner

BUILD-044 activates Calyx as a conservative autonomous runtime. It can seed durable missions, inspect queue depth, run one eligible task per cycle, log observations, evaluate outcomes, and expose runtime status for Mission Control.

The runtime is intentionally safe by default. It only executes non-destructive internal audit work. Deploy, merge, delete, overwrite, external-send, and cross-repository actions are approval-gated and remain `needs_review` until a human explicitly approves them.

## Runtime Endpoints

- `GET /api/runner/health` returns runtime metrics, queue counts, active orchestrator state, failures, and current mode.
- `GET /api/runner/summary` returns module registry rows, recent tasks, recent runs, runtime state, and orchestrator health.
- `GET /api/runner/autonomous-status` returns autonomous loop state plus orchestrator health.
- `POST /api/runner/start` enables and starts the autonomous runtime loop.
- `POST /api/runner/stop` stops and disables the autonomous runtime loop.
- `POST /api/runner/restart` restarts the autonomous runtime loop.
- `POST /api/runner/run-once` runs one full runtime cycle: heartbeat, mission seed, execute next eligible task.
- `POST /api/runner/execute-next` executes only the next eligible queued task.
- `POST /api/runner/seed-missions` creates the orchestrator schema and seeds safe default missions.

Compatibility endpoints are also available under `/api/orchestrator/*` for direct queue, agent, observation, and run inspection.

## Environment Variables

- `OC_RUNNER_AUTOLOOP=true` enables auto-start on FastAPI startup. Default is `false` for Render-safe behavior.
- `OC_RUNNER_INTERVAL_SECONDS=30` controls the autonomous cycle interval. Values below five seconds are raised to five seconds.
- `OC_RUNNER_ACTIVE_MODE=true` reports active/passive intent in runner health.
- `DATABASE_URL` is required for persistent queue, registry, runtime state, observations, and runs.

## Runtime Loop

Each autonomous cycle performs:

1. Heartbeat through the existing Calyx scheduler.
2. Mission seed and queue-depth inspection.
3. One eligible task execution.
4. Success/failure/needs-review recording.
5. Runtime metric update.

The runtime prevents duplicate worker threads. Shutdown uses the FastAPI shutdown hook to stop the background worker gracefully.

## Persistent Tables

All BUILD-044 tables live in `oc_admin`:

- `calyx_agents`
- `calyx_tasks`
- `calyx_observations`
- `calyx_runs`
- `calyx_runtime_state`

Task statuses are:

- `pending`
- `running`
- `completed`
- `failed`
- `blocked`
- `needs_review`

Evaluation results are:

- `pass`
- `fail`
- `needs_review`

## Mission Planner V1

`POST /api/runner/seed-missions` inserts default missions with stable task keys, so repeated seeding does not create duplicates:

- backend health check
- runner queue audit
- mycorrhiza cache audit
- relationship data audit
- image coverage audit
- frontend integration audit

Safe internal checks start as `pending`. Risky or cross-repository missions start as `needs_review`.

## Module Registry

The default registry exposes:

- `calyx_core`
- `health`
- `judging`
- `awards`
- `mycorrhiza`
- `mission_control`
- `relationship_audit`
- `image_coverage_audit`

Each module row includes name, capability, priority, enabled status, and allowed task types.

## Approval Gates

Calyx will not execute tasks whose task type, payload action, payload operation, or cross-repository marker implies:

- `deploy`
- `merge`
- `delete`
- `overwrite`
- `external_send`
- `cross_repository`

Approval-gated tasks are marked `needs_review`. Direct approval remains available through:

```bash
curl -X POST "$CALYX_URL/api/orchestrator/tasks/{task_id}/approve"
```

## Manual Operation

Seed missions:

```bash
curl -X POST "$CALYX_URL/api/runner/seed-missions"
```

Run one full cycle:

```bash
curl -X POST "$CALYX_URL/api/runner/run-once"
```

Execute the next task only:

```bash
curl -X POST "$CALYX_URL/api/runner/execute-next"
```

Start and stop the autonomous loop:

```bash
curl -X POST "$CALYX_URL/api/runner/start"
curl -X POST "$CALYX_URL/api/runner/stop"
```

Check status:

```bash
curl "$CALYX_URL/api/runner/health"
curl "$CALYX_URL/api/runner/summary"
```

## Frontend / Control Panel Display

No frontend changes are required for BUILD-044. A future control panel can display:

- `GET /api/runner/health` for enabled, running, thread alive, cycle count, last heartbeat, last execution, queue depth, completed count, failed count, and last error.
- `GET /api/runner/summary` for modules, tasks, runs, and orchestrator details.
- `POST /api/runner/start`, `/stop`, `/restart`, and `/run-once` as owner-only controls.
- `/api/orchestrator/tasks`, `/api/orchestrator/observations`, and `/api/orchestrator/runs` for detailed queue and activity views.
