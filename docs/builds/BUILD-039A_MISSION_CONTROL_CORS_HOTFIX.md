# BUILD-039A — Mission Control CORS hotfix

## Purpose

BUILD-039 added safe read-only Mission Control telemetry endpoints. The backend was redeployed, but the browser still reported Mission Control load/CORS failures from the deployed frontend.

BUILD-039A adds narrowly scoped CORS support for `/api/mission-control/*` telemetry routes.

## Allowed origins

- `https://orchid-continuum-frontend-vof6.onrender.com`
- `https://orchidcontinuum.org`
- `https://www.orchidcontinuum.org`

## Allowed methods

- `GET`
- `OPTIONS`

## Safety

This hotfix does not enable any write controls.

It does not enable:

- harvester run/pause/resume
- deploy actions
- credential access
- production writes
- destructive actions

Mission Control remains read-only unless a later build adds server-side owner authorization.

## Deployment

- Backend redeploy required after merge: yes
- Frontend redeploy required: no

## Validation

After merge and backend redeploy, refresh Mission Control and verify that `/api/mission-control/*` panels no longer report browser CORS/load failures.
