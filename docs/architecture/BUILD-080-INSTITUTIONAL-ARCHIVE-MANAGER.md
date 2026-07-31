# BUILD-080 — Institutional Archive Manager

## Purpose

BUILD-080 replaces experimental Colab archive notebooks with a permanent, resumable Calyx backend subsystem. It ingests institutional directories and ZIP archives without writing directly to canonical Knowledge Graph tables.

## Ownership boundaries

The archive subsystem owns source-file discovery, fingerprints, document extraction, structured parsing, provenance, checkpoints, archive-local entities and archive-local relationships. Semantic indexing and Knowledge Graph export are explicit interfaces only. Promotion into canonical scientific knowledge must pass through the existing governed review and publication systems.

## Components

- `scanner.py`: stable recursive traversal and path-safe ZIP extraction.
- `fingerprint.py`: streaming SHA-256 fingerprints.
- `extractor.py`: PDF, DOCX, Markdown, text, HTML and OCR-provider dispatch.
- `parser.py`: CSV, JSON and optional YAML parsing.
- `registry.py`: PostgreSQL document/file registry, deduplication, provenance and manifest generation.
- `checkpoint.py`: durable checkpoint state, defaulting to every 100 processed files.
- `entities.py` and `relationships.py`: pluggable extraction contracts with safe null implementations.
- `search.py`: registry queries plus semantic-index and graph-export interfaces.
- `importer.py`: orchestration, incremental imports, resume and per-file failure isolation.
- `routes.py`: authenticated mutation endpoints and read-only operational telemetry.

## Import lifecycle

1. Create an `archive_import_runs` record.
2. Scan a directory recursively or extract a ZIP into an isolated temporary directory.
3. Record the total number of files discovered.
4. Stream each file through SHA-256 fingerprinting.
5. Skip and record duplicates already present in `archive_files`.
6. Extract text or structured content.
7. Run configured entity and relationship extractors.
8. Atomically register the document, file, analysis and provenance.
9. Update Mission Control counters.
10. Persist a checkpoint after every configured interval, default 100 files.
11. Continue after individual file errors.
12. Mark the run completed or interrupted; `/archive/resume` continues from the durable file index.

## Database migration

Migration `106_institutional_archive_manager.sql` creates only:

- `archive_documents`
- `archive_files`
- `archive_entities`
- `archive_relationships`
- `archive_import_runs`
- `archive_provenance`
- `archive_checkpoints`

The migration is additive and idempotent. It does not alter existing Knowledge Graph, Candidate Knowledge, Literature Intelligence, Reasoning Ledger or publication tables. The rollback removes only BUILD-080 tables.

## API

### `POST /archive/import`

Owner/API-key protected. Accepts `source_path`, `checkpoint_interval` and `extract_zip`. The import runs as a FastAPI background task and returns HTTP 202.

### `POST /archive/resume`

Owner/API-key protected. Accepts `run_id`, validates that the run exists and resumes at the latest durable checkpoint.

### `GET /archive/status`

Returns the requested run or latest run, including:

- files discovered
- files processed
- duplicates skipped
- documents indexed
- entities extracted
- relationships created
- created, updated and finished timestamps
- error count and last error
- checkpoint file index, last path and state/elapsed time

### `GET /archive/statistics`

Returns registry totals for documents, files, entities, relationships and import runs.

### `GET /archive/documents`

Paginated archive document registry.

### `GET /archive/entities`

Paginated archive-local entity registry.

## Error handling

A bad file is recorded as an `archive_provenance` `file_error` event and increments the run error count. Processing continues with the next file. Run-level failures leave the run marked `interrupted` for explicit or automatic resume.

## Security and safety

- Import and resume require existing owner-session or API-key authentication.
- ZIP extraction rejects path traversal.
- Import paths are server-side paths; deployment policy must restrict accessible roots.
- SHA-256 identity drives cross-run duplicate detection.
- Canonical Knowledge Graph tables are never touched.
- OCR is a provider interface and reports `ocr_not_configured` when no provider is installed.

## Deployment prerequisites

1. Run migration 106 in staging.
2. Configure `DATABASE_URL` and existing Calyx authentication secrets.
3. Restrict allowed archive source roots at deployment level.
4. Configure optional PyYAML and OCR providers when those formats are required.
5. Run the dedicated PostgreSQL workflow successfully before production migration.
