# BUILD-079 Controlled Mission Queue and Autonomous Orchestration

BUILD-079 adds a durable mission-definition and queue layer that supplies bounded work to the existing autonomous runtime. It does not create a second worker loop.

## Current Runtime Architecture

- Runtime entry points live in `app/main.py` under `/api/runner/*`.
- The existing active loop is `runtime.runtime_engine.RuntimeEngine`.
- Startup starts one in-process thread when runtime configuration enables it.
- The runtime calls one heartbeat callback, one enqueue callback, and one execute callback on the configured interval.
- Legacy jobs use `oc_admin.ocp_execution_jobs`.
- Legacy `execute_next` already claims with `FOR UPDATE SKIP LOCKED`.
- Owner/API-key protected write routes use `verify_owner_or_api_key`.
- Mission Control telemetry is exposed through `app/routers/mission_control.py`.
- BUILD-044 tables still exist as earlier orchestration state, but the active loop is wired through `RuntimeEngine`.

BUILD-079 wraps the existing enqueue/execute callbacks so mission work is checked first, then the legacy queue continues to run when no mission job is available.

## Mission Lifecycle

States: `draft`, `awaiting_approval`, `approved`, `queued`, `running`, `paused`, `completed`, `failed`, `cancelled`, `expired`, `superseded`, `blocked`.

Draft and awaiting-approval missions cannot execute. High-risk missions require explicit owner approval, and controlled publication missions also require publication authority.

## Job Lifecycle

States: `pending`, `available`, `claimed`, `running`, `succeeded`, `retry_wait`, `failed`, `cancelled`, `dead_lettered`, `blocked`, `skipped`.

Jobs are claimed transactionally with `FOR UPDATE SKIP LOCKED`, leased to one worker, completed transactionally, and retried according to mission policy. Exhausted jobs move to `dead_letter_jobs`.

## Authorization

All mission and runtime queue routes use existing owner-session/API-key auth. Authorization is never inferred from mission creator alone.

## Safety Boundaries

- No arbitrary shell, SQL, Python, URL, or external API execution is supported.
- Taxonomy writes are prohibited for every registered mission type.
- Canonical graph writes are prohibited except for the explicit `controlled_publication` type, which remains subject to BUILD-078 dry-run/authority controls.
- Audit events are append-only.
- Telemetry is read-only and does not expose secrets.

## API

- `POST /api/missions`
- `GET /api/missions`
- `GET /api/missions/{mission_id}`
- `PATCH /api/missions/{mission_id}`
- `POST /api/missions/{mission_id}/submit`
- `POST /api/missions/{mission_id}/approve`
- `POST /api/missions/{mission_id}/reject`
- `POST /api/missions/{mission_id}/queue`
- `POST /api/missions/{mission_id}/pause`
- `POST /api/missions/{mission_id}/resume`
- `POST /api/missions/{mission_id}/cancel`
- `POST /api/missions/{mission_id}/retry`
- `GET /api/missions/{mission_id}/jobs`
- `GET /api/missions/{mission_id}/events`
- `POST /api/missions/{mission_id}/execute-one`
- `GET /api/mission-templates`
- `GET /api/runtime/queue`
- `GET /api/runtime/dead-letter`
- `POST /api/runtime/cycle`

## First Production-Safe Template

`Backend Health Audit` / `system_health_check` is seeded as a read-only mission template. It may inspect runtime, database, queue, graph counts, and taxonomy counts. It may not mutate taxonomy, publish graph records, ingest external sources, deploy, contact third parties, or run arbitrary commands.

## Recovery

Expired leases are returned to `available` by runtime cycles before enqueue/claim. Failed jobs retry until `maximum_attempts`, then enter `dead_letter_jobs` for owner inspection.

## Rollback

Rollback is additive: disable routes or mark templates inactive, then stop queuing missions. The migration only creates `oc_missions` structures and does not alter canonical graph, taxonomy, ontology, evidence, publication, or intake schemas.

## Known Limitations

Only read-only audit handlers are enabled initially. Domain write workflows are registered as explicit mission types but use the safe blocked handler until their existing subsystem-specific controls are connected.
