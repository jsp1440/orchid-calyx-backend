# BUILD-081 Implementation Report

## Outcome

BUILD-081 adds a metadata-only Brain Source Registry and Google Drive intake
module. It inventories Drive file metadata, detects duplicates, supports
incremental scans, records provenance and scan logs, and exposes dashboard
metrics. It does not download or export content, extract knowledge, build
embeddings, classify documents, mutate Drive files, or create graph nodes.

## Changed files

- `app/main.py`
- `app/source_registry/__init__.py`
- `app/source_registry/dependencies.py`
- `app/source_registry/drive.py`
- `app/source_registry/models.py`
- `app/source_registry/repository.py`
- `app/source_registry/routes.py`
- `app/source_registry/service.py`
- `docs/BUILD-081.md`
- `docs/BUILD-081-IMPLEMENTATION-REPORT.md`
- `migrations/081_brain_source_registry.sql`
- `requirements.txt`
- `tests/test_build_081_source_registry.py`

## Database migration

Apply `migrations/081_brain_source_registry.sql`. It creates the `oc_sources`
schema and these tables:

- `sources`: source identity, type, authentication method, health/status,
  configuration, last scan, and document counters.
- `document_inventory`: Drive ID, filename, folder path, MIME type, byte size,
  available checksum, timestamps, Drive version, inventory state, duplicate
  linkage, scan lineage, and provider provenance.
- `scan_logs`: start, finish, status, duration, error detail, processed,
  unchanged, duplicate, and failed counts.

Indexes support checksum/native-document duplicate lookup, processing-queue
queries, and scan history. Inventory states are `NEW`, `SCANNED`, `PROCESSED`,
`FAILED`, `DUPLICATE`, and `CHANGED`.

## Protected API

Every route requires the existing owner session or `X-API-Key` and uses the
existing Mission Control CORS policy.

- `POST /api/brain/sources/google-drive`
- `GET /api/brain/sources`
- `POST /api/brain/sources/{source_id}/scan`
- `GET /api/brain/sources/{source_id}/scans`
- `GET /api/brain/sources/dashboard/summary`

## Authentication and required configuration

Required for registry persistence and protected API access:

- `DATABASE_URL`: PostgreSQL connection containing the applied migration.
- `CALYX_API_KEY`: existing API-key protection, unless using an authenticated
  owner session.

Configure Drive metadata access using one of:

- `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`: the complete service-account JSON object
  as an environment-variable value; or
- Google Application Default Credentials. Locally, this is commonly selected
  with `GOOGLE_APPLICATION_CREDENTIALS` pointing to a credential JSON file.

The Drive identity must be granted read access to every configured root folder.
The adapter requests only `drive.metadata.readonly`.

Register a source before scanning:

```bash
curl -X POST "$BRAIN_API_URL/api/brain/sources/google-drive" \
  -H "X-API-Key: $CALYX_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"source_name":"Owner Google Drive","authentication_method":"SERVICE_ACCOUNT","folder_ids":["GOOGLE_DRIVE_FOLDER_ID"]}'
```

Run a metadata-only scan:

```bash
curl -X POST "$BRAIN_API_URL/api/brain/sources/SOURCE_ID/scan" \
  -H "X-API-Key: $CALYX_API_KEY"
```

View dashboard summary:

```bash
curl "$BRAIN_API_URL/api/brain/sources/dashboard/summary" \
  -H "X-API-Key: $CALYX_API_KEY"
```

## Real Drive scan status

No scan has been run against the owner's Google Drive. At finalization time,
`GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`, `GOOGLE_APPLICATION_CREDENTIALS`, and
`DATABASE_URL` were not configured in the implementation environment. The test
suite uses an in-memory fake Drive metadata gateway and does not access Drive.

## Verification

- BUILD-081 focused suite: `5 passed`.
- Full repository suite: `543 passed, 17 skipped`.
- `git diff --check`: passed.

