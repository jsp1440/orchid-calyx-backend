# BUILD-012D — Runtime Executor

BUILD-012D converts the BUILD-012C planner queue into executable runtime records.

## Purpose

Calyx can now:

- read the planner queue
- execute selected CDS modules through deterministic workers
- create execution records
- persist execution history as JSON files
- expose execution events, history, retry, and cancel APIs

This is the first version of the Runtime Executor. It is intentionally file-backed and safe for Render because it does not require `DATABASE_URL`.

## Added

- `runtime/runtime_executor.py`
- executor endpoints exposed through `runtime/planner_router.py`
- runtime execution records under `runtime/executions/` at runtime
- executor tests

## API endpoints

- `POST /api/runner/execute`
- `POST /api/runner/execute/{module_id}`
- `GET /api/runner/executions`
- `GET /api/runner/executions/{execution_id}`
- `GET /api/runner/history`
- `GET /api/runner/events`
- `POST /api/runner/retry/{execution_id}`
- `POST /api/runner/cancel/{execution_id}`

## Acceptance check after deploy

1. Open `/docs` and confirm the runner execution endpoints are visible.
2. Run `POST /api/runner/execute?limit=1`.
3. Run `GET /api/runner/executions`.
4. Run `GET /api/runner/history`.
5. Run `GET /api/runner/events`.

## Next build

BUILD-012E should persist execution records into `oc_admin` database tables and connect completed executions to Engineering Memory.
