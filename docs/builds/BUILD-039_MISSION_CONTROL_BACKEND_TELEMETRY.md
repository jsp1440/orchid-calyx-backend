# BUILD-039 — Mission Control Backend Live Telemetry API

## Purpose

BUILD-039 implements the first backend-side Mission Control telemetry provider for the Orchid Continuum.

BUILD-036 created the Mission Control UI. BUILD-037 and BUILD-038 made the frontend consume live telemetry when available and fall back honestly when endpoints are absent. BUILD-039 adds safe, read-only backend endpoints in `jsp1440/orchid-calyx-backend` so the frontend can begin leaving fallback mode.

## Safety posture

This build is read-only.

It does **not** enable:

- harvester run/pause/resume actions
- deploy actions
- credential access
- database writes
- production mutations
- destructive operations

Any future operational route must require server-side owner/admin authorization and must not rely on a frontend unlock code.

## Endpoints added

The telemetry router is mounted through the existing health router and exposes:

- `GET /api/mission-control/status`
- `GET /api/mission-control/subsystems`
- `GET /api/mission-control/audit`
- `GET /api/mission-control/harvesters`
- `GET /api/mission-control/repositories`
- `GET /api/mission-control/builds`
- `GET /api/mission-control/deployments`
- `GET /api/mission-control/metrics`
- `GET /api/mission-control/completeness`
- `GET /api/mission-control/recommendations`
- `GET /api/mission-control/governance`

These correspond to the BUILD-038 frontend contract.

## Data sources

The implementation uses safe read-only database probes through `DATABASE_URL` when available. It checks for known candidate tables with `to_regclass()` before counting rows.

Telemetry areas include:

- taxonomy
- occurrences / Atlas
- images and media
- literature
- ecological relationships
- mycorrhiza
- runtime execution jobs
- runtime action log

The endpoint returns blockers and partial status when a table is absent or the database is unavailable.

## Harvester heartbeat

Harvester rows are derived from `oc_admin.ocp_execution_jobs` when present. These are read-only heartbeat/status rows only. They do not execute jobs.

## Repository and deployment status

Repository/deployment endpoints currently return a safe registry with known blockers. Live GitHub and Render telemetry still require backend-owned read-only connector credentials.

## Remaining blocked work

BUILD-039 begins live telemetry but does not complete all observability.

Remaining work:

1. Add CORS verification for the deployed frontend origin if browser requests are still blocked.
2. Add backend-owned GitHub telemetry connector for latest commit, open PR count, and branch status.
3. Add backend-owned Render telemetry connector for deployment status and last deploy time.
4. Add source-specific freshness checks for Atlas, images, literature, relationships, and harvesters.
5. Add per-harvester checkpoint and row counts from actual pipeline logs.
6. Add owner/admin authorization before any operational write controls are exposed.

## Redeploy requirements

- Backend redeploy required after merge: **yes**
- Frontend redeploy required for this backend PR alone: **no**, assuming BUILD-038 frontend is already deployed

## Validation target

After merge and backend redeploy, Mission Control should no longer show `0/13 live endpoints` for the Calyx backend routes. It may still display mixed mode until GitHub/Render and deeper scientific telemetry are fully connected.
