# BUILD-053 - Backend Activation and Authentication Completion

## Activation Audit

BUILD-053 verifies the operational owner path created by BUILD-049 through BUILD-052. The backend now exposes authenticated owner session creation, persisted session validation, permissions, durable command records, operations queue transitions, source briefings, intelligence import/edit, audits, research requests, partnership packets, harvester mutations, Mission Control telemetry, and Executive Intelligence endpoints.

Operational:

- Owner session creation: `POST /api/mission-control/owner/session`
- Owner session validation: `GET /api/mission-control/owner/session`
- Owner permissions: `GET /api/mission-control/owner/permissions`
- Owner intelligence workspace, source briefings, commands, audits, queue, research requests, and partnership packets
- Harvester run once, pause, resume, retire, restore, and reassess through owner session or API key auth
- Executive state, summary, priorities, recommendations, changes, dependencies, and briefing
- Read-only Mission Control telemetry endpoints

Blocked by external credential or service:

- Production database persistence requires `DATABASE_URL` and applied migrations.
- Backend API-key writes require `CALYX_API_KEY`.
- Owner sessions require `CALYX_OWNER_ACCESS_CODE` and `CALYX_OWNER_SESSION_SECRET`.
- GitHub, Render, OAuth, calendar, and external partner telemetry require connector credentials not present in this repository.

Not yet implemented:

- Promotion of reviewed intelligence into authoritative Brain knowledge.
- Browser forms for harvester target/schedule/proposal selection.
- Automated partner API submission.

## Features Activated

- Persisted owner sessions are now validated server-side on reload via `GET /api/mission-control/owner/session`.
- The owner permissions contract now reports queue approval as an authenticated owner action with confirmation required.
- The permissions contract marks Brain knowledge promotion as `not_yet_implemented` instead of ambiguously disabled.

## Remaining External Dependencies

- `DATABASE_URL` for durable owner tables, runtime tables, queue tables, and privileged action logs.
- `CALYX_API_KEY` for server API-key authority.
- `CALYX_OWNER_ACCESS_CODE` for owner login.
- `CALYX_OWNER_SESSION_SECRET` for signed owner session tokens.
- GitHub/Render or equivalent deployment telemetry credentials for live repository/deployment status.
- OAuth credentials for any future third-party workspace integrations.

## Deployment Checklist

1. Apply BUILD-034, BUILD-044, BUILD-049, and BUILD-051 migrations in order.
2. Run BUILD-034/044/049 and BUILD-051 smoke SQL.
3. Configure `DATABASE_URL`, `CALYX_API_KEY`, `CALYX_OWNER_ACCESS_CODE`, and `CALYX_OWNER_SESSION_SECRET`.
4. Deploy the backend.
5. Smoke test owner login, session validation, permissions, command creation, queue transition, audit generation, research request creation, partnership packet generation, and one safe harvester mutation.
6. Deploy the frontend BUILD-053 branch after backend deployment.

## Required Secrets

- `DATABASE_URL`
- `CALYX_API_KEY`
- `CALYX_OWNER_ACCESS_CODE`
- `CALYX_OWNER_SESSION_SECRET`

## Required OAuth Credentials

None are required for the owner activation path completed by this build. External repository, deployment, calendar, mail, and partner integrations remain unavailable until their credentials are explicitly configured.

## Operational Readiness Assessment

Mission Control is operational for authenticated owner workflows once the backend is deployed with required secrets and migrations. Remaining unavailable features are either intentionally not implemented or require external credentials/services. No production-write route is enabled without backend owner session or API-key authorization.
