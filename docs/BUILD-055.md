# BUILD-055 - API Key Authentication, Runtime Activation, and Calyx Autonomous Operations

## 1. Authentication Model

BUILD-055 standardizes runtime write authorization on two server-side credentials: signed owner sessions for browser owner controls and `CALYX_API_KEY` for backend-to-backend administrative runtime calls. The frontend never receives the API key.

## 2. API Key Configuration

The canonical API key variable is `CALYX_API_KEY`. Runtime API-key validation reads it through `app.security.get_api_key()` and compares supplied `X-API-Key` values with `hmac.compare_digest`. Missing configuration fails closed with `API key authentication is not configured`.

## 3. Owner Session Bridge

Runtime write routes now accept `verify_owner_or_api_key`, allowing Mission Control bearer owner sessions to invoke approved controls without exposing `CALYX_API_KEY` to the browser.

## 4. Runtime Lifecycle

The existing in-process `RuntimeEngine` supports start, stop, restart, manual cycle execution, heartbeats, cycle counts, completed/failed counts, last completed/failed job names, queue depth, and current blocker reporting. Duplicate background workers are prevented per process by the engine lock and live thread check.

## 5. Autonomous Loop

The autonomous loop remains opt-in through runtime enable flags. Canonical enablement is `CALYX_AUTOLOOP_ENABLED=true`; legacy flags remain accepted for compatibility. The interval is read from `CALYX_RUNTIME_INTERVAL_SECONDS`, falling back to `OC_RUNNER_INTERVAL_SECONDS`, with a minimum of 5 seconds and safe 30-second default.

## 6. Runtime Endpoint Matrix

- `GET /api/runtime/configuration`: read-only secret-safe configuration diagnostic.
- `GET /api/runner/health`: read-only runtime health and configuration.
- `GET /api/runner/summary`: read-only queue and action summary.
- `GET /api/runner/autonomous-status`: read-only loop status.
- `POST /api/runner/run-once`: owner session or API key.
- `POST /api/runner/seed-missions`: owner session or API key.
- `POST /api/runner/execute-next`: owner session or API key.
- `POST /api/runner/execute-all`: owner session or API key plus constitutional review.
- `POST /api/runner/autonomous-cycle`: owner session or API key.
- `POST /api/runner/start`, `/stop`, `/restart`: owner session or API key plus constitutional review where high risk.
- Runtime planner, orchestrator, and constitutional write routes use the same owner-or-API-key dependency.

## 7. Scientific Job Classification

- Pollinator relationships: audit-only, blocked by source coverage.
- Mycorrhizal relationships: audit-only, blocked by source coverage.
- Literature extraction: audit-only, blocked by extraction source coverage.
- Ecological relationship graph: audit-only, blocked by graph completeness.
- TraitBank coverage: audit-only, blocked by source data.
- Conservation and habitat: audit-only, blocked by source data.
- Image/species evidence: audit-only, blocked by media evidence coverage.
- Frontend relationship integration: audit-only, checks integration readiness.
- Calyx core health: operational health check.
- Judging and awards maintenance: optional low-priority runtime support, not scientific completion.

## 8. Required Environment Variables

- `DATABASE_URL`: required for durable queue execution.
- `CALYX_API_KEY`: required for backend API-key runtime controls.
- `CALYX_OWNER_ACCESS_CODE`: required for browser owner login.
- `CALYX_OWNER_SESSION_SECRET`: required for signed owner sessions.
- `CALYX_AUTOLOOP_ENABLED`: canonical opt-in flag for autonomous loop startup.
- `CALYX_RUNTIME_INTERVAL_SECONDS`: canonical loop interval.

## 9. Render Configuration Steps

Set the variables above in Render service environment settings. Generate high-entropy values for `CALYX_API_KEY` and `CALYX_OWNER_SESSION_SECRET`; set `CALYX_OWNER_ACCESS_CODE` to an owner-managed access phrase. Do not paste secrets into logs, docs, PRs, or frontend variables.

## 10. Deployment Order

1. Merge and deploy backend BUILD-055.
2. Configure Render secrets.
3. Confirm `/api/runtime/configuration` reports configured booleans without values.
4. Deploy frontend BUILD-055 if Mission Control telemetry wiring is included.
5. Enable `CALYX_AUTOLOOP_ENABLED=true` only after manual runtime smoke tests pass.

## 11. Smoke Tests

- `GET /api/runtime/configuration` returns booleans and no secret values.
- Missing `CALYX_API_KEY` plus `X-API-Key` returns a safe configuration blocker.
- Invalid `X-API-Key` is rejected.
- Valid `X-API-Key` can call `/api/runner/autonomous-cycle`.
- Valid owner bearer session can call `/api/runner/autonomous-cycle`.
- Unauthenticated runtime write requests are rejected.
- `GET /api/runner/autonomous-status` shows heartbeat, cycle count, queue depth, completed/failed counts, and current blocker.
- `POST /api/runner/start`, `/stop`, and `/restart` do not create duplicate workers.

## 12. Remaining True Blockers

Production runtime cannot be honestly reported as running until Render has `DATABASE_URL`, owner session variables, and API key configured. In-process background loops are safe only for single web-worker deployment; multi-worker deployment requires a separate worker service or database-backed leadership lock.

## 13. Operational Readiness Assessment

Code-level authentication and runtime bridge work is complete. Production activation still requires owner-entered Render secrets and smoke tests against the deployed database.
