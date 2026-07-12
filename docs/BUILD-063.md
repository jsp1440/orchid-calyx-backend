# BUILD-063 — Owner Authentication Completion + Live Backend Activation

## Summary

BUILD-063 completes the owner authentication flow so that Mission Control can
restore an authenticated owner session after page refresh, and activates the
live backend control plane for runtime, queue, harvester, and audit operations.

**Before this build**

- Backend connected: YES
- Owner authenticated: NO
- Stored backend owner session rejected: Load failed
- Mission Control: read-only informational mode

**After this build**

- Backend connected: YES
- Owner authenticated: YES (session restore works on refresh)
- Mission Control: operational mode with live backend control

---

## Authentication Architecture Summary

### Cookie transport (primary)

| Attribute   | Value                                          |
|-------------|------------------------------------------------|
| Name        | `calyx_owner_session`                          |
| Path        | `/api/`                                        |
| HttpOnly    | `true`                                         |
| Secure      | `true` on Render or when `CALYX_OWNER_COOKIE_SECURE=true` |
| SameSite    | `none` when Secure=true (cross-origin), `lax` otherwise |
| TTL         | 3600 s default; configurable via `CALYX_OWNER_SESSION_TTL_SECONDS` (300–86400) |

### ****** transport (fallback)

The `/api/mission-control/owner/session-token` endpoint returns the signed
session token in the response body. Clients that cannot receive HttpOnly
cross-site cookies may store the token and send it as `Authorization: ****** on subsequent requests. `verify_owner_session` accepts both transports.

### Session token format

`base64url(owner|issued_at_unix|expires_at_unix|nonce).HMAC-SHA256`

Signed with `CALYX_OWNER_SESSION_SECRET`. Tampered or expired tokens are
rejected with structured 401 errors. Revoked nonces are tracked in-process via
`REVOKED_OWNER_NONCES`.

### CORS credentials

All Mission Control and owner endpoints are served through the health router
with the `add_mission_control_cors_headers` dependency, which adds:

```
Access-Control-Allow-Origin: <origin>
Access-Control-Allow-Credentials: true
Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, Authorization, X-API-Key, X-Orchid-Actor
```

Allowed origins: built-in set `ALLOWED_MISSION_CONTROL_ORIGINS` plus any
comma-separated values in `CORS_ALLOW_ORIGIN`. The wildcard `*` is never
reflected. Only exact-matching origins receive CORS headers.

**BUILD-063 addition:** CORS now also covers `/api/runner/*` and
`/api/harvesters/*` paths so authenticated runtime and harvester commands from
the browser succeed.

---

## Endpoint Inventory

### New endpoints (BUILD-063)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/mission-control/owner/executive-session` | None (auth-aware) | Comprehensive owner session state for Mission Control restore flow |
| `POST` | `/api/mission-control/owner/session/refresh` | Owner session or ****** Extend a valid session without re-login |

### Existing endpoints verified / enhanced

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| `POST` | `/api/mission-control/owner/session` | Access code | Sets HttpOnly cookie; credential_transport=httponly_cookie |
| `POST` | `/api/mission-control/owner/session-token` | Access code | Sets cookie + returns token in body; credential_transport=httponly_cookie_or_bearer |
| `GET` | `/api/mission-control/owner/session` | Optional | Inspect current session; 200 for both auth and unauth |
| `DELETE` | `/api/mission-control/owner/session` | Optional | Logout + revoke nonce + clear cookie |
| `GET` | `/api/mission-control/owner/permissions` | Owner or API key | Permission model |
| `POST` | `/api/runner/start` | Owner or API key | Runtime start — CORS added |
| `POST` | `/api/runner/stop` | Owner or API key | Runtime stop — CORS added |
| `POST` | `/api/runner/restart` | Owner or API key | Runtime restart — CORS added |
| `GET` | `/api/runner/health` | None | Runtime health — CORS added |
| `GET` | `/api/runner/autonomous-status` | None | Runtime status — CORS added |
| `POST` | `/api/calyx-queue` | Owner or API key | Enqueue job |
| `POST` | `/api/calyx-queue/{id}/cancel` | Owner or API key | Cancel job |
| `POST` | `/api/calyx-queue/{id}/retry` | Owner or API key | Retry job |
| `POST` | `/api/calyx-queue/{id}/pause` | Owner or API key | Pause job |
| `POST` | `/api/calyx-queue/{id}/resume` | Owner or API key | Resume job |
| `POST` | `/api/harvesters/{id}/run-once` | Owner or API key | Run harvester — CORS added |
| `POST` | `/api/harvesters/{id}/pause` | Owner or API key | Pause harvester — CORS added |
| `POST` | `/api/harvesters/{id}/resume` | Owner or API key | Resume harvester — CORS added |
| `POST` | `/api/harvesters/{id}/cancel` | Owner or API key | Cancel harvester — CORS added |
| `POST` | `/api/harvesters/{id}/reschedule` | Owner or API key | Reschedule harvester — CORS added |
| `POST` | `/api/mission-control/owner/audits` | Owner or API key | Generate audit (markdown/json/pdf/docx) |

### OPTIONS preflight handlers added (BUILD-063)

| Path pattern |
|---|
| `/api/runner/{full_path}` |
| `/api/harvesters/{full_path}` |

These join the existing preflight handlers for `/api/mission-control/*`,
`/api/executive/*`, `/api/scientific-intelligence/*`, and `/api/calyx-queue/*`.

---

## `GET /api/mission-control/owner/executive-session` — Response contract

Always returns HTTP 200. Mission Control reads `authenticated` to determine
operational mode.

```json
{
  "authenticated": true,
  "status": "authenticated",
  "owner": "owner",
  "auth_type": "owner_session",
  "issued_at": 1750000000,
  "expires_at": 1750003600,
  "reason": null,
  "credential_transport": "httponly_cookie_or_bearer",
  "allowedActions": {
    "runtimeStart":   { "allowed": true, "risk": "high", ... },
    "runtimeStop":    { "allowed": true, "risk": "high", ... },
    "runtimeRestart": { "allowed": true, "risk": "high", ... },
    "queueActions":   { "allowed": true, "risk": "high", ... },
    "generateAudit":  { "allowed": true, "risk": "low",  ... },
    "harvesters":     { "allowed": true, ... },
    ...
  },
  "permissions": ["runtime", "runtimeStart", "runtimeStop", ...],
  "session_info": {
    "refresh_available": true,
    "refresh_endpoint": "/api/mission-control/owner/session/refresh",
    "ttl_remaining_seconds": 3598
  },
  "backend": {
    "version": "BUILD-063",
    "build": "BUILD-063",
    "repository_revision": "a0fe562",
    "runtime_available": true,
    "runtime_enabled": false
  },
  "generated_at": "2026-07-12T08:45:29Z"
}
```

When unauthenticated, `authenticated` is `false`, all `allowedActions` have
`allowed: false`, `permissions` is `[]`, and `reason` is one of
`missing_session | expired | signed_out | invalid_session`.

---

## `POST /api/mission-control/owner/session/refresh` — Response contract

Requires a valid session (cookie or Bearer). Issues a fresh signed session with
a new TTL and sets a new HttpOnly cookie.

```json
{
  "authenticated": true,
  "status": "refreshed",
  "owner": "owner",
  "expires_at": 1750007200,
  "token": "cookie",
  "allowedActions": { ... },
  "credential_transport": "httponly_cookie"
}
```

Returns `401` if the current session is expired, revoked, or missing.

---

## Permission Model

`allowed_actions(authenticated: bool)` returns a structured map with every
owner-level action, its `allowed` boolean, risk level, whether it writes the
database, and whether it requires confirmation. The `executive-session` endpoint
surfaces this as both `allowedActions` (full objects) and `permissions` (flat
list of allowed action names) for Mission Control UI rendering.

Key permissions when authenticated:

| Action key | Description |
|---|---|
| `runtimeStart` | Start autonomous runtime worker |
| `runtimeStop` | Stop / disable autonomous runtime worker |
| `runtimeRestart` | Restart autonomous runtime worker |
| `autonomousCycle` | Trigger one autonomous cycle |
| `harvesters` | Run implemented harvester actions |
| `queueActions` | Approve / cancel / retry queue items |
| `audits` | Generate and persist live operational audits |
| `generateAudit` | Generate markdown/JSON/PDF/DOCX audit |
| `saveBriefing` | Persist source briefing and parsed intelligence |
| `submitCommand` | Create durable owner command record |
| `createResearchRequest` | Queue research request for analysis |
| `generatePartnershipPacket` | Generate and persist partner packet |

---

## Files Changed

| File | Change |
|---|---|
| `app/routers/owner_operations.py` | Added `import time, subprocess`; imported `create_owner_session_token`; added `_repo_revision()`, `_runtime_env_enabled()` helpers; added `GET /executive-session` and `POST /session/refresh` endpoints |
| `app/routers/health.py` | Added OPTIONS preflight handlers for `/api/runner/{full_path}` and `/api/harvesters/{full_path}` |
| `app/main.py` | Imported `add_mission_control_cors_headers`; added `RUNTIME_CORS` dependency list; added CORS dependency to harvesters router include, runner write endpoints (`RUNTIME_WRITE_AUTH`), and runner read endpoints (`/api/runner/health`, `/api/runner/autonomous-status`) |
| `tests/test_build_063_owner_auth.py` | New: 23 tests covering executive-session, session refresh, CORS, bearer auth, and full restore flow |
| `docs/BUILD-063.md` | This file |

---

## Validation Report

All 236 tests pass after BUILD-063 changes (213 pre-existing + 23 new).

```
python -m pytest tests/ --ignore=tests/test_autonomous_runner.py \
    --ignore=tests/test_build_034_044_049_integration.py -q
236 passed, 37 warnings
```

### Scenario coverage

| Scenario | Test | Status |
|---|---|---|
| Fresh login sets HttpOnly cookie | `test_cookie_session_login_inspect_logout_and_secret_safety` (BUILD-056) | ✅ |
| Page refresh — executive-session restores authenticated state | `test_full_session_restore_flow` | ✅ |
| Session refresh extends TTL without re-login | `test_session_refresh_extends_valid_session` | ✅ |
| Expired session detected as `reason: expired` | `test_executive_session_expired_session` | ✅ |
| Logout clears session and unauthenticates | `test_full_session_restore_flow` (step 5–6) | ✅ |
| Cookie persistence — HttpOnly on all auth cookies | `test_session_refresh_new_cookie_is_httponly` | ✅ |
| ****** fallback for browsers blocking cross-site cookies | `test_executive_session_bearer_token` | ✅ |
| Permission enforcement — unauthenticated actions denied | `test_executive_session_unauthenticated_allowed_actions_are_false` | ✅ |
| Permission model — all actions enabled when authenticated | `test_executive_session_authenticated_permissions_enabled` | ✅ |
| Runtime CORS preflight — start/stop/restart/status | `test_runner_*_cors_preflight` | ✅ |
| Harvesters CORS preflight | `test_harvesters_cors_preflight` | ✅ |
| CORS unknown origin not reflected | `test_runner_cors_unknown_origin_not_reflected` | ✅ |
| Runtime commands include CORS on response | `test_runner_authenticated_start_includes_cors_headers` | ✅ |
| Secrets not leaked via executive-session | `test_executive_session_does_not_leak_secrets` | ✅ |
| Refresh rejects expired session | `test_session_refresh_rejects_expired_session` | ✅ |
| Refresh rejects missing session | `test_session_refresh_requires_valid_session` | ✅ |

---

## Deployment Notes

### Required environment variables (unchanged from BUILD-056)

| Variable | Purpose |
|---|---|
| `CALYX_OWNER_ACCESS_CODE` | Owner login passphrase |
| `CALYX_OWNER_SESSION_SECRET` | HMAC signing secret for session tokens |
| `CALYX_API_KEY` | Server-side API key for automated runtime calls |
| `CORS_ALLOW_ORIGIN` | Comma-separated exact frontend origins (e.g. `https://orchid-continuum-frontend-vof6.onrender.com`) |
| `DATABASE_URL` | Required for queue persistence and runtime job tracking |

### Cookie configuration for cross-origin production

For cross-origin HTTPS deployments (Render backend ↔ Render frontend):

```
CALYX_OWNER_COOKIE_SECURE=true    # or leave unset; Render sets RENDER=1 automatically
CALYX_OWNER_COOKIE_SAMESITE=none  # required for cross-site cookie delivery
```

The `owner_cookie_secure()` function defaults to `true` on Render (when `RENDER`
env var is present) and `owner_cookie_samesite()` defaults to `none` when
secure. No manual override is required in standard Render deployments.

### Session restore for Mission Control

Mission Control should call `GET /api/mission-control/owner/executive-session`
on startup and after each page load. The `authenticated` field drives whether
the UI enters operational or read-only mode. If `authenticated` is `true`,
all `allowedActions` with `allowed: true` can be exercised immediately.

To silently refresh a session nearing expiry:
```
POST /api/mission-control/owner/session/refresh
```
No request body required. Cookies are sent automatically by the browser.

---

## Remaining Blockers

| Blocker | Impact | Resolution |
|---|---|---|
| `DATABASE_URL` not configured | Queue, runner summary, and some owner operations fall back to in-memory or return 503 | Set `DATABASE_URL` on Render and apply BUILD-051 migrations |
| Revoked nonces lost on restart | Signed-out sessions become valid again after server restart | Persisted nonce table or short TTL mitigates this in production |
| `recommendations` and `governance` actions marked `implemented: false` | Permission model exposes them as `allowed: false` | Implement in a future build |
| `promoteBrainKnowledge` not implemented | Executive briefing mutation not exposed | Future build |
| Multi-worker Render deployment | Autonomous runtime loop is in-process; a second worker breaks it | Use a separate worker service or DB-backed leadership lock |

---

## Recommended Next Build (BUILD-064)

1. **Persistent session revocation store** — move `REVOKED_OWNER_NONCES` to a
   database-backed set so logout persists across restarts.
2. **Governance and recommendations activation** — implement the two remaining
   `allowedActions` marked `implemented: false`.
3. **Brain knowledge promotion** — implement `promoteBrainKnowledge` endpoint.
4. **Multi-worker safety** — add DB-backed leadership lock for autonomous runtime.
5. **Session telemetry** — surface session activity and refresh history in the
   executive-session audit log.
