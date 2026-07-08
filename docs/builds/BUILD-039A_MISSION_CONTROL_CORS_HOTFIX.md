# BUILD-039A — Mission Control CORS hotfix

## Purpose

BUILD-039 added safe read-only Mission Control telemetry endpoints, but the deployed frontend continued to report browser load failures. Render showed the BUILD-039 backend deploy was live, so the likely remaining blocker was browser CORS access to `/api/mission-control/*`.

## Change

This hotfix scopes CORS response headers to read-only Mission Control telemetry routes mounted through `app/routers/health.py`.

Allowed browser origins:

- `https://orchid-continuum-frontend-vof6.onrender.com`
- `https://orchidcontinuum.org`
- `https://www.orchidcontinuum.org`

Allowed methods:

- `GET`
- `OPTIONS`

The change also adds an OPTIONS handler for `/api/mission-control/{full_path:path}` so browser preflight checks can succeed.

## Safety

This build does not enable write controls.

It does not enable:

- harvester run/pause/resume actions
- deploy actions
- credential access
- production writes
- destructive actions

Mission Control remains read-only unless server-side owner authorization is added in a later build.

## Deployment

Backend redeploy required after merge: yes.
Frontend redeploy required: no.

## Validation target

After merge and backend redeploy, Mission Control should stop reporting CORS/load failures for `/api/mission-control/*` endpoints. If fallback remains, the next blocker is likely endpoint payload shape or frontend environment configuration rather than basic browser access.
