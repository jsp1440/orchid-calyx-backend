# BUILD-012C — Runtime Planner

BUILD-012C connects the CDS Runtime Registry to a deterministic Runtime Planner.

## Purpose

Calyx can now inspect the CDS registry and produce:

- module discovery
- dependency graph
- execution plan
- runtime queue

This moves Calyx from static registry reporting toward autonomous orchestration.

## Added

- `runtime/runtime_planner.py`
- `runtime/planner_router.py`
- FastAPI wiring for planner endpoints
- planner tests

## API endpoints

- `GET /api/runner/discovery`
- `GET /api/runner/dependencies`
- `GET /api/runner/plan`
- `GET /api/runner/queue`
- `POST /api/runner/rebuild-plan`

## Behavior

The planner reads CDS modules, scores them by status, domain, and priority relevance, then builds a queue of selectable modules.

Selectable statuses:

- `live-ready`
- `framework`
- `prototype`

Skipped statuses:

- `planned`
- unknown values

## Acceptance check after deploy

1. Open `/docs` and confirm the `Calyx Runtime Planner` tag appears.
2. Run `GET /api/runner/discovery`.
3. Run `GET /api/runner/plan`.
4. Run `GET /api/runner/queue`.
5. Confirm `DatabaseInspector` is queued and planned modules are skipped with reasons.

## Next build

BUILD-012D should connect planner queue output to real `oc_admin.ocp_execution_jobs` records so the Runtime Engine can execute planner-selected CDS jobs rather than hard-coded optimization placeholders.
