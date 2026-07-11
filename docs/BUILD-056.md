# BUILD-056 Owner Authentication

## Render backend environment

Required: `DATABASE_URL`, `CALYX_API_KEY`, `CALYX_OWNER_ACCESS_CODE`,
`CALYX_OWNER_SESSION_SECRET`, `CALYX_AUTOLOOP_ENABLED`,
`CALYX_RUNTIME_INTERVAL_SECONDS`, and `CORS_ALLOW_ORIGIN` (comma-separated exact
frontend origins; never `*` when credentials are enabled).

Optional cookie controls are `CALYX_OWNER_SESSION_TTL_SECONDS` (300–86400),
`CALYX_OWNER_COOKIE_SECURE` (defaults true on Render), and
`CALYX_OWNER_COOKIE_SAMESITE` (defaults `none` on Render for cross-origin HTTPS).

## Render frontend environment

Retain `VITE_API_BASE_URL` (or the repository's existing public backend URL
equivalent) and `VITE_MAPBOX_TOKEN` only when intentionally browser-public.
Remove `VITE_MISSION_CONTROL_ACCESS_CODE`, `CALYX_API_KEY`,
`CALYX_OWNER_ACCESS_CODE`, `CALYX_OWNER_SESSION_SECRET`, `DATABASE_URL`, and any
private third-party secret.

Deploy backend first, verify `/api/runtime/configuration`, then deploy frontend.
Smoke test: open Mission Control signed out; confirm writes are disabled; sign in;
confirm the diagnostic panel says `Owner Session Active` and `HttpOnly cookie`;
run one autonomous cycle and one supported harvester action; sign out; confirm the
same writes return 401 and the UI returns to read-only mode.
