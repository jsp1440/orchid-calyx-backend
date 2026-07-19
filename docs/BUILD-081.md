# BUILD-081 — Brain Source Registry and Google Drive Intake

This Brain module inventories Google Drive metadata only. It never downloads,
exports, moves, modifies, or deletes Drive files and never creates graph nodes,
classifications, embeddings, or extracted knowledge.

## Setup

1. Apply `migrations/081_brain_source_registry.sql`.
2. Install dependencies from `requirements.txt`.
3. Set either `GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` to a service-account JSON
   object or configure Google Application Default Credentials.
4. Grant that identity read access to each registered root folder.

The adapter requests only `drive.metadata.readonly`. Register a source with
`POST /api/brain/sources/google-drive`, then invoke
`POST /api/brain/sources/{source_id}/scan`. All module routes retain the
existing owner-or-API-key security and Mission Control CORS policy.

Incremental scans compare Drive file identity, modified time, checksum, name,
and path. Unchanged rows are only marked as seen. New and changed files update
the processing queue; duplicate rows retain a `duplicate_of_id` link and no
source file is removed. Binary files use Drive checksums. Google-native files,
which expose no content checksum in metadata, use a conservative metadata
fingerprint and are never exported for comparison.

`GET /api/brain/sources/dashboard/summary` returns total sources/documents,
processed documents, duplicates, failures, last scan time, and queue depth.
Per-source scan logs include start, finish, errors, duration, processed,
unchanged, duplicate, and failed counts.

