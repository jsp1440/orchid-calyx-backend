# BUILD-080C — Archive Production Hardening

## Purpose

Harden the Institutional Archive Manager before it is activated against real institutional files.

## Security boundary

Archive imports are disabled unless `ARCHIVE_ALLOWED_ROOTS` contains one or more approved server-side directories separated by the operating-system path separator. Every requested source is resolved before authorization; symlink and path traversal escapes therefore fail the descendant check.

Resource limits are deployment-configurable:

- `ARCHIVE_MAX_FILE_BYTES`
- `ARCHIVE_MAX_ZIP_MEMBERS`
- `ARCHIVE_MAX_ZIP_UNCOMPRESSED_BYTES`
- `ARCHIVE_MAX_ZIP_EXPANSION_RATIO`
- `ARCHIVE_MAX_PATH_DEPTH`

ZIP imports are rejected before extraction when member count, expanded size, expansion ratio, individual member size, path depth, or destination containment violates policy.

## Execution controls

Migration 107 adds queued, cancelling and cancelled states plus cancellation, heartbeat, lease, attempt and dispatcher metadata. A run must be claimed before processing. The claim is conditional and prevents two workers from executing the same run concurrently. Active workers refresh their lease at checkpoints. Expired leases can be recovered to `interrupted` through an authenticated endpoint.

The default dispatcher is a bounded local thread pool with one worker. It is intentionally isolated behind `ArchiveDispatcher` so the existing durable runtime queue can replace it without changing the API or importer. `ARCHIVE_LOCAL_WORKERS` is restricted to 1–4.

## Cancellation and recovery

`POST /archive/cancel/{run_id}` sets a durable cancellation request. The importer checks it between files, writes a checkpoint, releases the lease and ends the run as `cancelled`.

`POST /archive/recover-stale` marks runs with expired worker leases as `interrupted`, making them eligible for controlled resume.

## API additions

- `GET /archive/runs`
- `GET /archive/manifest/{run_id}`
- `GET /archive/documents/{document_id}`
- document text/title filtering through `GET /archive/documents?q=`
- entity label/type filtering through `GET /archive/entities?q=&entity_type=`
- `POST /archive/cancel/{run_id}`
- `POST /archive/recover-stale`

Import, resume, cancellation and stale-run recovery reuse the existing owner/API-key guard.

## Migration order

Apply migration 106 before migration 107. Migration 107 is additive and idempotent. Its rollback removes only hardening columns and indexes; it does not remove archive documents or files.

## Deployment requirements

1. Configure `ARCHIVE_ALLOWED_ROOTS` to a dedicated, least-privilege mount.
2. Keep unrestricted host filesystem paths out of the allowlist.
3. Apply migration 107 in staging and validate cancellation, stale recovery and duplicate execution rejection.
4. Replace the local dispatcher with the durable worker queue before high-volume imports.
5. Do not connect archive graph export directly to production Knowledge Graph writes.
