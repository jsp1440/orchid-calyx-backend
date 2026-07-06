# BUILD-044: Calyx Autonomous Orchestrator

BUILD-044 adds a durable orchestration layer so Calyx can receive work, queue it, assign it to enabled agents, execute safe tasks, log observations, evaluate outcomes, and report status to Mission Control.

## Endpoints

- `POST /api/orchestrator/seed` creates the orchestrator schema and inserts default agents/tasks.
- `GET /api/orchestrator/health` returns queue counts, active agent, last run, failures, and approval-gated action names.
- `GET /api/orchestrator/agents` lists registered agents and their allowed task types.
- `GET /api/orchestrator/tasks` lists queued and historical tasks.
- `POST /api/orchestrator/tasks` creates a task. Risky task types are placed in `needs_review`.
- `POST /api/orchestrator/tasks/{task_id}/approve` releases a reviewed task back to `pending`.
- `POST /api/orchestrator/run-once` selects the next eligible task and executes it.
- `GET /api/orchestrator/observations` lists what Calyx inspected, changed, skipped, or failed.
- `GET /api/orchestrator/runs` lists run history.

## Persistent Tables

All BUILD-044 tables live in `oc_admin`:

- `calyx_agents`
- `calyx_tasks`
- `calyx_observations`
- `calyx_runs`

Task statuses are `pending`, `running`, `completed`, `failed`, `blocked`, and `needs_review`.

Evaluation results are `pass`, `fail`, and `needs_review`.

## Approval Gates

Calyx will not execute tasks whose task type or payload action is one of:

- `deploy`
- `merge`
- `delete`
- `overwrite`
- `external_send`

Those tasks are marked `needs_review` until a human approves them with:

```bash
curl -X POST "$CALYX_URL/api/orchestrator/tasks/{task_id}/approve"
```

## Manual Operation

Seed defaults:

```bash
curl -X POST "$CALYX_URL/api/orchestrator/seed"
```

Run one safe task:

```bash
curl -X POST "$CALYX_URL/api/orchestrator/run-once"
```

Check status:

```bash
curl "$CALYX_URL/api/orchestrator/health"
```

Create a task:

```bash
curl -X POST "$CALYX_URL/api/orchestrator/tasks" \
  -H "Content-Type: application/json" \
  -d '{
    "task_type": "backend_health_check",
    "title": "Check backend health",
    "payload": {"requested_by": "Mission Control"},
    "priority": 50
  }'
```

## Frontend / Control Panel Display

The frontend does not need to implement orchestration logic. It should display:

- `GET /api/orchestrator/health` for queue counts, active agent, last run, and failures.
- `GET /api/orchestrator/tasks` for a task table.
- `GET /api/orchestrator/agents` for registry state.
- `GET /api/orchestrator/observations` for the activity log.
- `POST /api/orchestrator/run-once` for an owner-only manual run button.
- `POST /api/orchestrator/tasks/{task_id}/approve` for owner-only approval gates.

## Seed Tasks

BUILD-044 seeds four minimal tasks:

- frontend audit
- backend health check
- image coverage audit
- relationship data audit

The first two can complete using internal checks. Image and relationship audits intentionally return `needs_review` until live coverage metrics are connected.
