# BUILD-066A — Owner Control Verification

**Branch:** `feature/build-066a-backend-owner-control`  
**Status:** ✅ Complete (backend)

---

## Overview

BUILD-066A adds the Mission Control **owner control verification** flow to the backend:

| Method | Path | Auth | Persistence |
|--------|------|------|-------------|
| `POST` | `/api/mission-control/owner/control-verification` | Owner session | `oc_admin.build066a_control_verifications` |
| `GET`  | `/api/mission-control/owner/control-verification/:id` | Owner session | Reads same table |

Both endpoints require an authenticated owner session (cookie or bearer token).

---

## Required Render Environment Variables

Set all of the following in your Render service **Environment** settings. Do **not** expose values in logs or documentation.

| Variable | Purpose | Required |
|----------|---------|----------|
| `CALYX_OWNER_ACCESS_CODE` | Secret code used to authenticate as the owner | ✅ |
| `CALYX_OWNER_SESSION_SECRET` | HMAC secret for signing/verifying owner session tokens | ✅ |
| `DATABASE_URL` | PostgreSQL connection URL (e.g., `******host/db`) | ✅ |
| `FRONTEND_ORIGIN` | Allowed CORS origin for the frontend (see below) | Recommended |
| `CORS_ALLOW_ORIGIN` | Comma-separated additional CORS origins (supplements the built-in set) | Optional |
| `CALYX_OWNER_COOKIE_SECURE` | Set `true` on Render (default: auto-detected via `RENDER` env var) | Optional |
| `CALYX_OWNER_SESSION_TTL_SECONDS` | Session TTL in seconds (default `3600`; range `300–86400`) | Optional |

> **Note:** `FRONTEND_ORIGIN` is documented here for reference. The backend currently uses the built-in `ALLOWED_MISSION_CONTROL_ORIGINS` set plus `CORS_ALLOW_ORIGIN`. If your frontend origin changes, add it to `CORS_ALLOW_ORIGIN`.

---

## CORS Configuration

The backend is pre-configured to allow credentialed cross-origin requests from:

```
https://orchid-continuum-frontend-vof6.onrender.com
https://orchidcontinuum.org
https://www.orchidcontinuum.org
http://localhost:5174
http://127.0.0.1:5174
```

**Response headers set on allowed origins:**

```
Access-Control-Allow-Origin: <matched origin>
Access-Control-Allow-Credentials: true
Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: accept, Content-Type, Authorization, X-API-Key, X-Orchid-Actor
Access-Control-Max-Age: 86400
Vary: Origin
```

To add additional origins without code changes, set the `CORS_ALLOW_ORIGIN` environment variable:

```
CORS_ALLOW_ORIGIN=https://your-custom-origin.example.com
```

---

## Cookie / Auth Session Configuration

Cookies are configured automatically:

| Attribute | Value |
|-----------|-------|
| Name | `calyx_owner_session` |
| Path | `/api/` |
| HttpOnly | `true` |
| Secure | `true` on Render (or when `CALYX_OWNER_COOKIE_SECURE=true`) |
| SameSite | `none` when Secure=true; `lax` otherwise |

---

## Database Migration

Run the migration SQL before first use (idempotent — safe to re-run):

```sql
-- migrations/BUILD-066A-owner-control-verification.sql
CREATE TABLE IF NOT EXISTS oc_admin.build066a_control_verifications (
    id               TEXT        PRIMARY KEY,
    label            TEXT        NOT NULL,
    session_owner    TEXT        NOT NULL,
    read_back_confirmed BOOLEAN  NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

The table is also created automatically on first use if it does not exist (the endpoints run `CREATE TABLE IF NOT EXISTS` within the handler).

---

## Deployment Checklist

- [ ] Set `CALYX_OWNER_ACCESS_CODE` in Render environment
- [ ] Set `CALYX_OWNER_SESSION_SECRET` in Render environment
- [ ] Set `DATABASE_URL` in Render environment
- [ ] Confirm `RENDER` env var is set (Render sets this automatically) or set `CALYX_OWNER_COOKIE_SECURE=true`
- [ ] Deploy/redeploy the service on Render
- [ ] Run the migration SQL (or allow the auto-create to run on first request)
- [ ] Execute the verification procedure below

---

## Verification Procedure

### Step 1 — Authenticate as owner (cookie transport)

```bash
curl -c /tmp/calyx_cookies.txt -X POST \
  https://orchid-calyx-backend.onrender.com/api/mission-control/owner/session \
  -H "Content-Type: application/json" \
  -H "Origin: https://orchid-continuum-frontend-vof6.onrender.com" \
  -d '{"access_code": "<CALYX_OWNER_ACCESS_CODE>"}' \
  -v
```

**Expected response (HTTP 200):**
```json
{
  "authenticated": true,
  "status": "authenticated",
  "owner": "owner",
  "expires_at": 1750003600,
  "token": "cookie",
  "allowedActions": { "..." },
  "credential_transport": "httponly_cookie"
}
```

### Step 1 (alternative) — ****** transport

```bash
TOKEN=$(curl -s -X POST \
  https://orchid-calyx-backend.onrender.com/api/mission-control/owner/session-token \
  -H "Content-Type: application/json" \
  -d '{"access_code": "<CALYX_OWNER_ACCESS_CODE>"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
echo "Token: $TOKEN"
```

### Step 2 — POST: create control verification record

With cookie:
```bash
curl -b /tmp/calyx_cookies.txt -X POST \
  https://orchid-calyx-backend.onrender.com/api/mission-control/owner/control-verification \
  -H "Content-Type: application/json" \
  -H "Origin: https://orchid-continuum-frontend-vof6.onrender.com" \
  -d '{"label": "BUILD-066A production verification"}' \
  -v
```

With bearer token:
```bash
curl -X POST \
  https://orchid-calyx-backend.onrender.com/api/mission-control/owner/control-verification \
  -H "Content-Type: application/json" \
  -H "Authorization: ******" \
  -H "Origin: https://orchid-continuum-frontend-vof6.onrender.com" \
  -d '{"label": "BUILD-066A production verification"}' \
  -v
```

**Expected response (HTTP 200):**
```json
{
  "id": "CV-<16-hex-chars>",
  "label": "BUILD-066A production verification",
  "created_at": "2026-07-13T05:18:01.000000+00:00",
  "session_owner": "owner",
  "read_back_confirmed": true
}
```

Note the `id` value for Step 3.

### Step 3 — GET: read-back verification record

```bash
RECORD_ID="CV-<id-from-step-2>"

# With cookie:
curl -b /tmp/calyx_cookies.txt \
  "https://orchid-calyx-backend.onrender.com/api/mission-control/owner/control-verification/$RECORD_ID" \
  -H "Origin: https://orchid-continuum-frontend-vof6.onrender.com" \
  -v

# With bearer token:
curl \
  "https://orchid-calyx-backend.onrender.com/api/mission-control/owner/control-verification/$RECORD_ID" \
  -H "Authorization: ******" \
  -H "Origin: https://orchid-continuum-frontend-vof6.onrender.com" \
  -v
```

**Expected response (HTTP 200):**
```json
{
  "id": "CV-<same-id>",
  "label": "BUILD-066A production verification",
  "created_at": "2026-07-13T05:18:01.000000+00:00",
  "session_owner": "owner",
  "read_back_confirmed": true
}
```

### Step 4 — CORS preflight check

```bash
curl -X OPTIONS \
  https://orchid-calyx-backend.onrender.com/api/mission-control/owner/control-verification \
  -H "Origin: https://orchid-continuum-frontend-vof6.onrender.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: authorization, content-type, accept" \
  -v
```

**Expected response headers (HTTP 200):**
```
Access-Control-Allow-Origin: https://orchid-continuum-frontend-vof6.onrender.com
Access-Control-Allow-Credentials: true
Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: accept, Content-Type, Authorization, X-API-Key, X-Orchid-Actor
```

---

## Expected Error Responses

| Scenario | Status | Body |
|----------|--------|------|
| No session / bad token | `401` | `{"detail": "Owner session is required"}` |
| Invalid access code | `401` | `{"detail": "Invalid owner access code"}` |
| Missing `label` | `422` | Pydantic validation error |
| Empty `label` | `422` | Pydantic validation error |
| Record not found | `404` | `{"detail": "Control verification '<id>' not found"}` |
| DB write failure | `503` | `{"detail": "BUILD-066A database write failed: ..."}` |
| DB read failure | `503` | `{"detail": "BUILD-066A database read failed: ..."}` |

---

## Production Verification Checklist

Use this checklist to confirm end-to-end functionality after deployment:

- [ ] `GET /health` returns HTTP 200
- [ ] `POST /api/mission-control/owner/session` with correct access code returns HTTP 200 and sets `calyx_owner_session` cookie
- [ ] `POST /api/mission-control/owner/control-verification` with valid session returns HTTP 200 with `read_back_confirmed: true`
- [ ] Response includes `id`, `label`, `created_at`, `session_owner`
- [ ] `GET /api/mission-control/owner/control-verification/:id` returns HTTP 200 for the same `id`
- [ ] Retrieved record matches created record
- [ ] CORS preflight from `https://orchid-continuum-frontend-vof6.onrender.com` returns correct headers
- [ ] `Access-Control-Allow-Credentials: true` is present in preflight response
- [ ] `accept` is listed in `Access-Control-Allow-Headers`
- [ ] Unauthorized request (no session) returns HTTP 401
- [ ] GET for unknown ID returns HTTP 404

---

## Files Modified (BUILD-066A)

| File | Change |
|------|--------|
| `app/routers/owner_operations.py` | Added `CONTROL_VERIFICATIONS` in-memory store; `ControlVerificationRequest` model; `POST /control-verification`; `GET /control-verification/{id}` |
| `app/routers/health.py` | Added `accept` to `Access-Control-Allow-Headers` |
| `migrations/BUILD-066A-owner-control-verification.sql` | Idempotent migration for `oc_admin.build066a_control_verifications` |
| `tests/test_build_066a_owner_control_verification.py` | 26 tests covering success, auth, CORS, read-back, error paths |
| `docs/BUILD-066A.md` | This document |
