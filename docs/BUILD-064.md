# BUILD-064 — Production Operations Activation

## Summary

BUILD-064 activates the production operations layer for the Orchid Continuum
backend.  Three capabilities previously scaffolded with `implemented=False` are
now fully operational.  A persistent session revocation store is added so that
logout survives server restarts.  The Mission Control BUILD_ID is advanced to
`BUILD-064` and the Kernel registry is updated with a BUILD-064 entry.

**Before this build**

- `recommendations` action — `not_yet_implemented`
- `governance` action — `not_yet_implemented`
- `promoteBrainKnowledge` action — `not_yet_implemented`
- Session nonce revocation — in-memory only (lost on restart)
- Mission Control BUILD_ID — `BUILD-039`

**After this build**

- `recommendations` action — `owner_authorized_action` ✅
- `governance` action — `owner_authorized_action` ✅
- `promoteBrainKnowledge` action — `owner_authorized_action` ✅
- Session nonce revocation — persisted to `oc_admin.build064_session_revocations` with in-memory fallback ✅
- Mission Control BUILD_ID — `BUILD-064` ✅

---

## Architecture

### Activated capabilities

All three previously scaffolded actions in `allowed_actions()` (in
`app/routers/owner_operations.py`) had `implemented=False`, which caused them
to return `allowed: false` even for authenticated owners.  BUILD-064 removes
that flag and wires each action to a new authenticated endpoint.

| Action | Was | Now | Endpoint |
|---|---|---|---|
| `recommendations` | `not_yet_implemented` | `owner_authorized_action` | `GET /api/mission-control/owner/recommendations` |
| `governance` | `not_yet_implemented` | `owner_authorized_action` | `GET /api/mission-control/owner/governance` |
| `promoteBrainKnowledge` | `not_yet_implemented` | `owner_authorized_action` | `POST /api/mission-control/owner/intelligence/{item_id}/promote` |

### Persistent session revocation

`REVOKED_OWNER_NONCES` is a module-level `set[str]` in `app/security.py`.
Previously, logout added the nonce to this set only in-memory.  After a server
restart the nonce would disappear, allowing a stolen session to be replayed.

BUILD-064 adds:

- **`persist_revoked_nonce(nonce)`** — adds to in-memory set AND writes to
  `oc_admin.build064_session_revocations`.  DB write is best-effort; failures
  are silently absorbed so logout always succeeds even without a database.
- **`load_revoked_nonces()`** — reads all revocations from the last 7 days from
  the DB into the in-memory set.  Called from `app.on_event("startup")`.
- The DB table is created with `CREATE TABLE IF NOT EXISTS` on first use, so no
  migration file is required.

In-memory set remains the hot-path check inside `_decode_owner_token`.  Once
loaded on startup, revoked nonces are available synchronously without any DB
round-trip per request.

### Endpoint design

#### `GET /api/mission-control/owner/recommendations`
- **Auth**: owner session or API key
- **Wraps**: existing read-only `GET /api/mission-control/recommendations`
- **Adds**: `owner` identity, `allowedActions`, `review_status`, `generated_at`
- **Note**: Recommendation approval actions are reserved for a future build

#### `GET /api/mission-control/owner/governance`
- **Auth**: owner session or API key
- **Wraps**: existing read-only `GET /api/mission-control/governance`
- **Adds**: `owner` identity, `allowedActions`, `mutation_status`, `generated_at`
- **Note**: Governance mutations (policy changes, decision overrides) are
  reserved for a future build; this endpoint enables authenticated read access

#### `POST /api/mission-control/owner/intelligence/{item_id}/promote`
- **Auth**: owner session or API key
- **Body**: `{ "confirm": true, "notes": "optional" }`
- **Precondition**: item `verification_state` must be `provisional`, `reviewed`,
  or `owner_reviewed`
- **Effect**: sets `verification_state = "promoted"`, records `promoted_by` and
  `promoted_at`, appends notes, writes to privileged action log
- **Returns**: `{ "status": "promoted", "item": {...}, "allowedActions": {...} }`
- **Errors**:
  - `400` if `confirm` is not `true`
  - `404` if item_id does not exist
  - `409` if item is already in a non-promotable state (already promoted,
    blocked, etc.)

---

## Implementation

### Files modified

| File | Change |
|---|---|
| `app/routers/owner_operations.py` | Removed `implemented=False` from `recommendations`, `governance`, `promoteBrainKnowledge`; updated labels; added `persist_revoked_nonce`, `_db_execute_silent`, `load_revoked_nonces` helpers; updated `delete_session` to call `persist_revoked_nonce`; added `GET /recommendations`, `GET /governance`, `POST /intelligence/{id}/promote` endpoints; bumped backend metadata to BUILD-064 |
| `app/routers/mission_control.py` | Updated `BUILD_ID` from `"BUILD-039"` to `"BUILD-064"` |
| `app/main.py` | Added `load_revoked_nonces()` call in `startup_event` for DB-backed nonce reload |
| `runtime/kernel_registry.py` | Updated `KERNEL_UPDATED_AT`; added `build-064` entry in `builds()` registry |
| `tests/test_build_051_owner_operations.py` | Updated `test_persisted_owner_session_can_be_validated` to assert `promoteBrainKnowledge` is now `allowed=True` |
| `tests/test_mission_control_telemetry.py` | Updated BUILD_ID assertion from `"BUILD-039"` to `"BUILD-064"` |
| `tests/test_build_064_production_operations.py` | New: 24 tests (see below) |
| `docs/BUILD-064.md` | This file |

---

## Validation

### Test results

```
python3 -m pytest tests/ \
    --ignore=tests/test_autonomous_runner.py \
    --ignore=tests/test_build_034_044_049_integration.py \
    -q
260 passed, 35 warnings in 5.02s
```

236 pre-existing tests pass (no regressions).
24 new BUILD-064 tests pass.

### New test coverage (tests/test_build_064_production_operations.py)

| Test | Status |
|---|---|
| `test_allowed_actions_recommendations_now_implemented` | ✅ |
| `test_allowed_actions_governance_now_implemented` | ✅ |
| `test_allowed_actions_promote_brain_knowledge_now_implemented` | ✅ |
| `test_unauthenticated_all_actions_still_false` | ✅ |
| `test_owner_recommendations_requires_auth` | ✅ |
| `test_owner_recommendations_returns_200_when_authenticated` | ✅ |
| `test_owner_recommendations_includes_allowed_actions` | ✅ |
| `test_owner_governance_requires_auth` | ✅ |
| `test_owner_governance_returns_200_when_authenticated` | ✅ |
| `test_owner_governance_policies_present` | ✅ |
| `test_promote_requires_auth` | ✅ |
| `test_promote_requires_confirm_true` | ✅ |
| `test_promote_not_found_returns_404` | ✅ |
| `test_promote_success_updates_verification_state` | ✅ |
| `test_promote_returns_allowed_actions` | ✅ |
| `test_promote_already_promoted_returns_409` | ✅ |
| `test_persist_revoked_nonce_adds_to_memory` | ✅ |
| `test_load_revoked_nonces_returns_zero_without_db` | ✅ |
| `test_delete_session_revokes_nonce_persistently` | ✅ |
| `test_mission_control_build_id_is_064` | ✅ |
| `test_mission_control_status_reflects_064` | ✅ |
| `test_executive_session_backend_build_is_064` | ✅ |
| `test_kernel_registry_includes_build_064` | ✅ |
| `test_kernel_registry_build_064_capabilities` | ✅ |

### Scenario coverage

| Scenario | Test | Status |
|---|---|---|
| Unauthenticated owner — all actions false | `test_unauthenticated_all_actions_still_false` | ✅ |
| Authenticated owner — recommendations/governance/promote allowed | `test_allowed_actions_*` | ✅ |
| Owner recommendations endpoint accessible | `test_owner_recommendations_*` | ✅ |
| Owner governance endpoint accessible | `test_owner_governance_*` | ✅ |
| Brain knowledge promotion: confirm required | `test_promote_requires_confirm_true` | ✅ |
| Brain knowledge promotion: not found | `test_promote_not_found_returns_404` | ✅ |
| Brain knowledge promotion: success | `test_promote_success_updates_verification_state` | ✅ |
| Brain knowledge promotion: idempotent conflict | `test_promote_already_promoted_returns_409` | ✅ |
| Session nonce revocation persists in-memory | `test_persist_revoked_nonce_adds_to_memory` | ✅ |
| Nonce load from DB returns 0 without DATABASE_URL | `test_load_revoked_nonces_returns_zero_without_db` | ✅ |
| Full logout flow revokes session | `test_delete_session_revokes_nonce_persistently` | ✅ |
| BUILD_ID = BUILD-064 | `test_mission_control_build_id_is_064` | ✅ |
| executive-session backend.build = BUILD-064 | `test_executive_session_backend_build_is_064` | ✅ |
| Kernel registry has build-064 entry | `test_kernel_registry_includes_build_064` | ✅ |

---

## Endpoint Inventory

### New endpoints (BUILD-064)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/api/mission-control/owner/recommendations` | Owner or API key | Authenticated review of live Mission Control recommendations |
| `GET` | `/api/mission-control/owner/governance` | Owner or API key | Authenticated read of governance state (north star, policies, decisions) |
| `POST` | `/api/mission-control/owner/intelligence/{item_id}/promote` | Owner or API key | Promote reviewed intelligence item to authoritative Brain knowledge |

### All existing endpoints preserved

All endpoints from BUILD-051 through BUILD-063 are preserved without breaking
changes.  The `allowedActions` map in session/permissions/executive-session
responses now includes three additional `allowed: true` entries for
authenticated owners.

---

## Deployment Notes

No new required environment variables beyond those established in BUILD-056.

| Variable | Purpose |
|---|---|
| `CALYX_OWNER_ACCESS_CODE` | Owner login passphrase |
| `CALYX_OWNER_SESSION_SECRET` | HMAC signing secret for session tokens |
| `CALYX_API_KEY` | Server-side API key for automated runtime calls |
| `DATABASE_URL` | When set, session revocations are persisted; revoked nonces are reloaded on startup |

### Session revocation table

The table `oc_admin.build064_session_revocations` is created automatically with
`CREATE TABLE IF NOT EXISTS` on first logout after deployment.  No manual
migration is required.

```sql
CREATE TABLE IF NOT EXISTS oc_admin.build064_session_revocations (
    nonce TEXT PRIMARY KEY,
    revoked_at TIMESTAMPTZ DEFAULT NOW()
);
```

Only nonces revoked within the last 7 days are reloaded on startup, which
bounds the memory footprint in long-lived deployments.

---

## Remaining Blockers

| Blocker | Impact | Resolution |
|---|---|---|
| `DATABASE_URL` not configured | Session revocations remain in-memory only; persistent nonce reload is skipped | Set `DATABASE_URL` on Render and apply migrations |
| `recommendations` approval mutations not yet built | Owner can read recommendations but cannot approve or reject | Future build |
| `governance` structural mutations not yet built | Owner can read governance state but cannot add policies or decisions | Future build |
| `promoteBrainKnowledge` has no downstream Brain integration | Item `verification_state` is updated but no Brain knowledge graph is written | Future build: wire to Brain/Atlas graph write |
| Revoked nonces lost if DB unavailable | Nonces only persisted in-memory without DATABASE_URL | Mitigated by short TTL; resolved by configuring DATABASE_URL |

---

## Recommended Next Build (BUILD-065)

1. **Brain knowledge graph write** — after promotion, create or update a Brain
   knowledge graph node so that the promoted intelligence becomes discoverable
   via `/api/scientific-intelligence/` queries.
2. **Recommendation approval workflow** — add `PATCH /owner/recommendations/{id}`
   to allow the owner to mark a recommendation as approved, deferred, or
   rejected, and surface the decision in governance.
3. **Governance decision write** — add `POST /owner/governance/decisions` to
   create a new owner-signed governance decision that appears in the governance
   telemetry payload.
4. **Session revocation expiry** — add a periodic cleanup job (or DB trigger)
   to remove revocation records older than 7 days.
5. **Multi-worker leadership lock** — add a DB-backed leadership lock for the
   autonomous runtime loop so that a second Render worker does not run a
   duplicate cycle.
