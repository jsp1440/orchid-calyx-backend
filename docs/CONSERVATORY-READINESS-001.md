# CONSERVATORY-READINESS-001 — Persistent Storage and Restart Gate

## Completed

- Added an owner-gated live readiness report at `GET /api/conservatory/readiness`.
- Added a persisted restart probe and post-restart verification contract.
- Added fail-closed gates for writable storage, non-temporary path, persistent-volume declaration, and restart survival.
- Added focused tests and CI.

## Restart certification workflow

1. Configure `CALYX_CONSERVATORY_DIR` on the mounted persistent volume.
2. Set `CALYX_CONSERVATORY_STORAGE_PERSISTENT=true` only after the mount is verified.
3. Call `POST /api/conservatory/readiness/restart-probe` and retain the returned token.
4. Restart or redeploy the backend.
5. Call `POST /api/conservatory/readiness/restart-probe/verify` with the token.
6. Confirm `GET /api/conservatory/readiness` returns `ready_for_collection_entry=true`.

The probe cannot certify within the same process boot. The token and certification receipt must survive on the configured storage path.

## Brain record

Production collection entry remains blocked until storage is writable, outside the temporary filesystem, explicitly declared persistent, and proven to survive a real backend restart. Code merge alone is not treated as operational readiness.
