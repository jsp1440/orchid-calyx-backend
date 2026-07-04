# BUILD-014 — Autonomous Discovery

BUILD-014 teaches Calyx to inspect its own repository and derive a live inventory of runtime modules, API routers, workers, capabilities, dependency hints, schedules, and recommendations.

## Added

- `runtime/autonomous_discovery.py`
- `runtime/discovery_router.py`
- Discovery endpoints exposed through the existing `/api/runner` router
- Discovery tests

## API endpoints

- `GET /api/runner/discover`
- `POST /api/runner/discover`
- `GET /api/runner/modules`
- `GET /api/runner/capabilities`
- `GET /api/runner/graph`
- `GET /api/runner/recommendations`
- `GET /api/runner/schedule`
- `GET /api/runner/discovery-dashboard`
- `POST /api/runner/rebuild`

## Behavior

The discovery engine scans repository Python files under `runtime/` and `app/`, parses AST metadata, detects classes/functions/FastAPI route decorators/import dependencies, infers capabilities, builds a dependency graph, writes a file-backed discovery cache, and generates recommendations.

## Acceptance check after deploy

1. Run `POST /api/runner/discover`.
2. Run `GET /api/runner/modules`.
3. Run `GET /api/runner/capabilities`.
4. Run `GET /api/runner/graph`.
5. Run `GET /api/runner/recommendations`.
6. Confirm the response build is `BUILD-014` and the module count is greater than zero.

## Next build

BUILD-015 should persist discovery snapshots into the Brain and begin autonomous repair workflows for degraded modules and missing dependencies.
