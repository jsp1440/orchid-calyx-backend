# BUILD-039 Mission Control Backend Telemetry

## Endpoints implemented

The backend exposes the read-only Mission Control telemetry interface through the existing health router:

- `GET /api/mission-control/subsystems`
- `GET /api/mission-control/health`
- `GET /api/mission-control/builds`
- `GET /api/mission-control/harvesters`
- `GET /api/mission-control/runtime`
- `GET /api/mission-control/governance`
- `GET /api/mission-control/recommendations`

The existing telemetry router also preserves compatible read-only endpoints for status, audit, repositories, deployments, metrics, and completeness.

## Telemetry sources

- `DATABASE_URL` read-only probes, when configured.
- `to_regclass()` checks before table reads so missing tables degrade to structured blockers.
- Candidate taxonomy, occurrence, media, literature, relationship, mycorrhiza, runtime job, and runtime action tables.
- `oc_admin.ocp_execution_jobs` for harvester heartbeat/status when present.
- `oc_admin.ocp_runtime_actions` for runtime action telemetry when present.
- Static repository/deployment/governance registries where backend-owned connectors are not yet configured.

## Safety posture

These endpoints are telemetry only. They do not deploy, pause, resume, enqueue, execute, update, delete, or mutate production data. They do not expose tokens, credentials, or secrets. Operational controls remain disabled and must require server-side owner authorization in a future build.

## Remaining stubs

- GitHub repository state is a safe registry stub until a backend-owned read-only GitHub connector is approved.
- Render/deployment state is a safe registry stub until a backend-owned read-only deployment connector is approved.
- Harvester row counts and checkpoints are placeholders unless runtime job tables contain source-specific details.
- Freshness and provenance checks are row-count based until source-specific telemetry is wired.
- Brain runtime health remains a future adapter.

## Future connector work

- Add read-only GitHub telemetry for default branch, latest commit, PR count, and workflow status.
- Add read-only Render telemetry for backend deployment status and last deploy time.
- Add source-specific freshness checks for Atlas, images, literature, relationship graph, and mycorrhizal data.
- Add owner/admin authorization before any write-capable Mission Control action routes are considered.

## Deployment

Backend deployment is required after merge so the deployed Mission Control frontend can call these backend routes. No frontend deployment is required for this backend-only change.
