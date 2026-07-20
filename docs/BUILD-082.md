# BUILD-082 — Controlled Google Drive Document Import

## Operator guide

BUILD-082 imports owner-approved BUILD-081 registry records into the BUILD-076A Universal Intake tables. It does not scan Drive, recurse folders, accept file paths/URLs, extract text, create embeddings or ontology records, or mutate the Knowledge Graph.

Set `GOOGLE_DRIVE_PILOT_FOLDER=/Pilot/` (the default) and configure the BUILD-081 source with only the registered `Orchid Continuum Brain Intake/Pilot` folder. Add authenticated owner identifiers to `configuration.approved_importers`. Preview each registry ID, then import it explicitly. The development pilot is limited to:

1. `BUILD-INFRA-004 Architecture Review.pdf`
2. `comprehensive_orchid_glossary.pdf`
3. `Copy of Mijinyawa's CV.docx`

No credentials or document bytes are logged. Drive access is read-only.

## OAuth permissions

Content import requires `https://www.googleapis.com/auth/drive.readonly`. BUILD-081 metadata scans continue to use `drive.metadata.readonly`. The gateway exposes only `get_media` and `export_media`; it has no delete, rename, move, sharing, or write operation.

## Formats

Supported: PDF, DOCX, Google Docs (exported as DOCX), TXT, and Markdown. CSV and Google Sheets content are not enabled in this build; Sheets remain BUILD-081 metadata only. Unsupported MIME types return `UNSUPPORTED_FORMAT` without retrieving content.

## API

All endpoints require the existing owner-session or API-key authentication.

- `POST /api/brain/imports/preview` — validate a registry ID without content retrieval.
- `POST /api/brain/imports` — import one `{registry_id, mission_id?}`.
- `POST /api/brain/imports/batch` — import 1–25 unique registry IDs.
- `GET /api/brain/imports/history?registry_id=` — immutable revision history.
- `POST /api/brain/imports/{session_id}/retry/{registry_id}` — retry `RETRYABLE` retrievals.
- `POST /api/brain/imports/{session_id}/cancel` — cancel a pending session.

Mission Control uses mission type `controlled_drive_import`. Its entire input manifest must be `{ "registry_ids": [1, 2] }`; extra keys, raw paths, URLs, SQL, and commands are rejected.

## Idempotency, duplicate, revision, and retry behavior

SHA-256 is computed over downloaded/exported bytes. A rerun of the same registry ID and hash returns `UNCHANGED` and creates no record. A hash already belonging to another registry record creates a `DUPLICATE` revision linked to the canonical revision. Changed bytes create the next revision number and preserve history. Transient Drive failures become `RETRYABLE`; other failures become `FAILED`. Only retryable items can use the retry endpoint. Pending sessions can be cancelled.

## Migration and validation

Apply, in order: `076a_universal_intake.sql`, `079_controlled_mission_orchestration.sql`, `081_brain_source_registry.sql`, and `082_controlled_drive_document_import.sql`. The BUILD-082 migration is additive and idempotent (`IF NOT EXISTS`) and creates import sessions, immutable document revisions, a hash index, transition audit records, and retry tracking with foreign keys and indexes.

For controlled PostgreSQL validation, use a disposable database and synthetic registry rows unless owner credentials are explicitly supplied:

1. Record row counts in `oc_graph`, `oc_ontology`, and `oc_semantic` before validation.
2. Apply the migration twice and confirm both runs succeed.
3. Insert a synthetic Pilot-folder PDF and DOCX registry item and use a fake read-only gateway.
4. Verify Universal Intake rows, SHA-256, byte count, all provenance keys, revision history, duplicate/unchanged results, and transition audit order.
5. Confirm the three protected schema counts are unchanged and no extracted text or embedding is produced.

The live three-document pilot requires explicit owner Drive credentials and registry IDs. It must not be simulated as a successful live acceptance test.

## Known limitations and BUILD-083 notes

- Import execution is synchronous; a later worker can consume the same service contract.
- Revision bytes are stored in PostgreSQL to keep the first controlled pipeline atomic. BUILD-083 may add an immutable object-store adapter while retaining Universal Intake as the sole document record.
- Google Sheets content and CSV are intentionally deferred.
- BUILD-083 may initiate semantic review only from explicitly approved intake revision IDs. It must preserve provenance, never auto-publish, and keep ontology/graph writes behind their existing gates.

