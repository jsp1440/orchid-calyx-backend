# BUILD-049 Runtime Integration Readiness

## Dependency And Conflict Matrix

| PR | Role | Depends On | Overlap | Conflict / Resolution |
| --- | --- | --- | --- | --- |
| #18 BUILD-034 | Constitutional evaluator, autonomy levels, missions, decision ledger, governance questions | Main already contains the module | `app/main.py`, `runtime/router_fastapi.py`, constitutional routes | Keep `runtime/constitutional_orchestrator.py` as canonical. Add `/api/runner/constitutional/*` only as a compatibility alias to the same singleton evaluator. Fix high-risk policy bypass. |
| #19 BUILD-044 | Durable task queue, agent registry, observations, run logs, runtime enabled state, worker metrics | #18 policy evaluator | `app/main.py`, `app/routers/health.py`, `runtime/runtime_engine.py` | Keep one `RuntimeEngine`. Add BUILD-044 durable queue under `/api/orchestrator/*`. Preserve existing `/api/runner/*` endpoints and add aliases for start/stop/restart/seed. Do not mount routers through `health.py` when `app/main.py` owns them. |
| #33 BUILD-049 | Harvester registry, run history, target proposals, adaptive routing, owner-gated actions | #18 evaluator, #19 audit vocabulary | `app/routers/health.py`, governance concepts | Mount `/api/harvesters/*` once from `app/main.py`. Keep API-key authorization. Harvester high-risk operations call the constitutional evaluator and return decision records. |
| Frontend #39 | Accessible Mission Control and read-only harvester control display | Backend #33 and integration branch | Mission Control response model | No backend authority is granted by browser unlock. Controls remain disabled unless backend fields explicitly allow an action. |

Required merge order: integration PR #34 first supersedes backend PRs #18, #19, and #33 after review. Frontend PR #39 follows backend deployment.

## Canonical Architecture

- Constitutional policy evaluation: `runtime.constitutional_orchestrator.orchestrator`.
- Autonomy levels and owner approval gates: `AutonomyLevel` plus policy-driven evaluation; high-risk policy membership forces review even when a caller requests a lower autonomy level.
- Mission registry, decision ledger, and governance questions: constitutional orchestrator singleton.
- Durable task queue, runtime enabled state, agent/module registry, observations, and run logs: `runtime.autonomous_orchestrator.CalyxAutonomousOrchestrator` under `/api/orchestrator/*`.
- Worker lifecycle and runtime metrics: single `runtime.runtime_engine.RuntimeEngine`. The worker does not auto-start by default; startup requires an explicit true enable flag and still respects disable flags.
- Harvester registry, run history, and target proposals: `runtime.harvester_control.control_plane`.
- API-key authorization: `app.security.verify_api_key` for every state-changing route under `/api/runner/*`, `/api/runtime/*` constitutional evaluation, `/api/orchestrator/*`, and `/api/harvesters/*`.
- Allowed-action contract: read models expose disabled `allowedActions` records with `allowed=false`, `state=requires_owner_authorization`, `auth=api_key_required`, risk, and reason.
- Mission Control telemetry: `app.routers.mission_control` behind scoped read-only CORS in `app.routers.health`.

Compatibility aliases retained:

- `/api/runtime/constitutional/*` and `/api/runner/constitutional/*` both call the same constitutional orchestrator.
- `/api/runner/autonomous-start`, `/api/runner/autonomous-stop`, `/api/runner/start`, `/api/runner/stop`, and `/api/runner/restart` all manage the same runtime engine.

## Migration Order

1. Backup production database.
2. Apply `migrations/BUILD-034-constitutional-orchestrator.sql` if it has not already been applied.
3. Apply `migrations/BUILD-044-calyx-autonomous-orchestrator.sql`.
4. Apply `migrations/BUILD-049-harvester-command-center.sql`.
5. Run `migrations/BUILD-034-044-049-smoke-test.sql` with `psql`.

The BUILD-044 and BUILD-049 migrations use `CREATE ... IF NOT EXISTS`, `ALTER ... ADD COLUMN IF NOT EXISTS`, and `CREATE INDEX IF NOT EXISTS` patterns where possible. They are wrapped in explicit transactions. Rollback is limited: after data is written to `oc_admin.calyx_*` or harvester tables, rollback should be a restore-from-backup or a reviewed data migration, not an automatic destructive down migration.

Required environment variables:

- `DATABASE_URL`
- `CALYX_API_KEY`
- Optional: `OC_RUNNER_INTERVAL_SECONDS`, `OC_RUNNER_AUTOLOOP`, `CALYX_RUNTIME_ENABLED`, `AUTONOMOUS_RUNTIME_ENABLED`, `RUNNER_ENABLED`, `CALYX_AUTONOMOUS_ENABLED`, and matching disable flags.

Runtime enablement is fail-stopped: if all enable flags are absent, `AUTO_LOOP_ENABLED=false` and startup imports/health checks do not start a worker. An explicit true enable flag is required, and any true disable flag wins.

## Route And Authorization Inventory

Read-only constitutional:

- `GET /api/runner/constitutional/status`
- `GET /api/runner/constitutional/policies`
- `GET /api/runner/constitutional/missions`
- `GET /api/runner/constitutional/decision-ledger`
- `GET /api/runner/constitutional/governance-questions`
- Compatibility: same concepts under `/api/runtime/constitutional/*`.

State-changing constitutional:

- `POST /api/runner/constitutional/evaluate` and `POST /api/runtime/constitutional/evaluate`.
- Authentication: `Depends(verify_api_key)`.
- Policy evaluation: always uses the canonical constitutional evaluator.
- Unauthorized response: 401 when `CALYX_API_KEY` is absent, missing from the request, or invalid.

Runtime and orchestrator:

- Read: `GET /api/runner/health`, `/api/runner/summary`, `/api/runner/autonomous-status`, `/api/orchestrator/health`, `/api/orchestrator/agents`, `/api/orchestrator/tasks`, `/api/orchestrator/observations`, `/api/orchestrator/runs`.
- State-changing: `POST /api/runner/start`, `/stop`, `/restart`, `/autonomous-start`, `/autonomous-stop`, `/autonomous-cycle`, `/run-once`, `/execute-next`, `/execute-all`, `/seed-missions`, planner/executor/discovery POSTs under `/api/runner/*`, `/api/orchestrator/seed`, `/api/orchestrator/tasks`, `/api/orchestrator/tasks/{task_id}/approve`, `/api/orchestrator/run-once`.
- Authentication: `Depends(verify_api_key)` on each route.
- Policy/approval: route handlers record constitutional decisions. Runtime start/restart/bulk execute and orchestrator approval/run-once are high-risk terms and return `review_required` before mutation.
- Unauthorized response: 401 when `CALYX_API_KEY` is absent, missing from the request, or invalid.
- Read models: `/api/runner/health`, `/api/runner/summary`, `/api/runner/autonomous-status`, and orchestrator read responses include `allowedActions`.

Harvesters:

- Read: `GET /api/harvesters`, `GET /api/harvesters/{id}`, `GET /api/harvesters/{id}/runs`, `GET /api/harvesters/{id}/recommendation`.
- State-changing: `POST /api/harvesters/{id}/run-once`, `/pause`, `/resume`, `/retire`, `/restore`, `/target-proposals`, `/target-proposals/{proposal_id}/approve`, `/target-proposals/{proposal_id}/reject`, `PATCH /api/harvesters/{id}/schedule`, `POST /api/harvesters/{id}/reassess`.
- Authentication: `Depends(verify_api_key)`.
- Policy/approval: target changes, schedule changes, retirement, restoration, and proposal decisions call constitutional evaluation and are review-gated when high-risk policy applies.
- Expected unauthorized response: 401 when API key is required and absent/invalid.
- Expected authorized response: JSON status plus harvester/proposal/run payload and, where applicable, decision record.
- Read models: harvester payloads include `allowedActions` for `runOnce`, `pause`, `resume`, `retire`, `restore`, `changeTarget`, `changeSchedule`, `approve`, `reject`, and `reassess`; all are disabled until the backend receives authenticated mutation requests.

Mission Control:

- Read-only telemetry routes remain under `/api/mission-control/*` with scoped CORS.
- Browser unlock is not backend authorization.

## Smoke Tests

After deploy:

1. `GET /health`
2. `GET /api/runner/constitutional/status`
3. Unauthenticated `POST /api/runner/constitutional/evaluate`; expect 401.
4. Authenticated `POST /api/runner/constitutional/evaluate` with `action=delete production records`, `requested_autonomy_level=1`; expect `review_required`, `risk_level=high`.
5. `GET /api/orchestrator/health`; verify `allowedActions` is present and disabled.
6. Unauthenticated `POST /api/orchestrator/seed`; expect 401.
7. Authenticated `POST /api/orchestrator/seed`; expect seeded agents/tasks or a clear `DATABASE_URL` configuration error.
8. `GET /api/harvesters`; ensure `allowedActions` is present and no secrets are present.
9. Unauthenticated `POST /api/harvesters/gbif/pause`; expect 401.
10. Authenticated harvester `pause`, `resume`, `run-once`; expect audit-shaped JSON and no credential disclosure.
11. `GET /api/runner/autonomous-status`; expect stopped worker unless explicit runtime enablement was configured.
12. `GET /api/mission-control/harvesters`; frontend should render read-only safely.

## Deployment Checklist

1. Confirm `DATABASE_URL` points to the intended production database and take a backup.
2. Set `CALYX_API_KEY` in the backend runtime environment before exposing state-changing routes.
3. Leave all runtime enable flags unset for first deploy unless owner approval explicitly authorizes autonomous start.
4. Apply BUILD-034, BUILD-044, and BUILD-049 migrations in order.
5. Run `migrations/BUILD-034-044-049-smoke-test.sql`.
6. Deploy the backend branch and confirm startup logs show no autonomous worker start unless explicitly enabled.
7. Run the HTTP smoke tests above.
8. Deploy frontend PR #39 only after backend smoke tests pass and verify browser controls remain disabled unless backend `allowedActions` contract changes.
9. Do not merge superseded backend PRs #18, #19, or #33 after this integration PR lands.

## Superseded PRs

After this integration PR is reviewed and shown to contain the required functionality, backend PRs #18, #19, and #33 can be closed as superseded.
