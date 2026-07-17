# BUILD-076A universal intake foundation

Verdict: PARTIALLY COMPLETE. This change delivers a safe, review-first batch intake slice. Durable background processing, production object storage, specialist binary parsers, version similarity, and the full batch/document review UI remain for BUILD-076B.

## Audit findings

- BUILD-070 already provided owner/API-key protected pasted-text and URL intake, deterministic candidate extraction, review, and an explicit no-graph-mutation publication boundary. The router was nested indirectly through the health router; BUILD-076A registers it once at the `app/main.py` composition point to avoid duplicate routes and circular imports.
- BUILD-072 workflow routing and BUILD-074 executive recommendation tables are reusable; no separate grants system was warranted.
- Existing file storage used a hash plus unsanitized user filename, wrote synchronously, and overwrote the same path. It had no production object-storage adapter contract.
- No durable queue backs intake. Render-local files are not durable unless a persistent disk is mounted.
- The existing extractor recognizes only binomials as species and requires contextual evidence. File intake in this build does not promote extracted taxa at all.
- The repository default tree contains Windows-invalid root filenames (`alth.py, ` and an extremely long React-source filename), requiring `core.protectNTFS=false`, long paths, or a repository cleanup before normal Windows checkout.

## Architecture and behavior

- Physical storage: immutable, private, content-addressed originals under `INTAKE_STORAGE_DIR/sha256/...`; SHA-256 is the storage identity and filenames are display metadata only.
- Logical organization: additive ingestion batch, document, and document-event records. Documents preserve candidate type, relevance, dates, grants, external sources, provenance, duplicate links, and a permanent default prohibition on canonical promotion.
- Safe text extraction is initially limited to UTF-8 TXT, Markdown, CSV, and validated JSON. PDF, DOCX, XLSX, images, and ZIP are preserved and marked for a specialist parser. ZIPs are inspected but not expanded; traversal, encryption, malformed archives, entry-count limits, and expanded-size limits are enforced.
- Exact duplicates are linked by SHA-256 and retained. Semantic version detection is deferred.
- Grant candidates remain unreviewed and preserve the future `grant -> commitment/deliverable -> milestone -> evidence -> status -> deadline` model. Completion is never calculated.
- URLs are candidate external sources with offsets and `contacted=false`; no network call is made.
- All routes inherit owner/API-key authorization. Original retrieval is private and uses attachment/no-store headers.

## Endpoints

- Existing: `POST /api/intake/text`, `POST /api/intake/url`, review/detail/approve/reject/publish.
- Added: `POST /api/intake/batches` (multipart, HTTP 207 partial-success response), `GET /api/intake/batches`, `GET /api/intake/batches/{id}`, `PATCH /api/intake/documents/{id}/review`, `GET /api/intake/documents/{id}/original`.

## Migration and deployment

Apply `migrations/070_knowledge_intake.sql`, then `migrations/076a_universal_intake.sql`. The 076A migration is additive. Its manual rollback order is events, documents, then batches; rollback deletes 076A metadata and must not be run without an explicit retention decision.

Required configuration:

- `DATABASE_URL`: existing private PostgreSQL connection.
- `INTAKE_STORAGE_DIR`: private durable mounted storage. Render ephemeral filesystem is not acceptable for production originals.
- `INTAKE_MAX_FILE_BYTES`: optional, default 52,428,800 bytes. Align the Render/proxy body limit above this value plus multipart overhead.

Object storage credentials are intentionally not fabricated. Before production, add an S3-compatible private adapter or a backed-up Render persistent disk, retention monitoring, storage-growth alerts, and a durable worker/queue. This implementation processes basic classification during the upload request and does not claim durable background processing.

## Manual iPad acceptance

1. Sign into the owner Intelligence Center in Safari on iPadOS.
2. Under Upload files, enter a batch name and optional source label.
3. Tap Choose files; in Files, open a folder, use Select, choose several mixed supported files, and tap Open.
4. Verify every selected filename appears; remove one accidental selection with its 44px remove control.
5. Upload and verify the preserved/duplicate/failed totals and any per-file errors.
6. Reload the page and verify the existing Paste Text and review queue still work. (Batch reopening UI is deferred; verify `GET /api/intake/batches/{id}` through an authenticated client.)
7. Upload the same file again and verify it is retained as a duplicate record rather than overwritten or deleted.
8. Verify an unsupported or oversized item fails without losing successful files in the same batch.

## Deferred BUILD-076B scope

- Durable per-file jobs, retry/reprocess execution, resumable/direct-to-object-storage uploads, and live per-file transfer progress.
- Full batch list/detail and document review screens, bulk controls, project/collection links, event history, grant and external-source candidate views.
- Sandboxed PDF/DOCX/XLSX parsers, image metadata/OCR policy, and safe ZIP child-document expansion.
- MIME magic-byte validation, antivirus/content-disarm policy, duplicate race hardening with a database constraint/advisory lock, and object-storage integration tests.
- Rank-aware canonical taxonomy lookup/unresolved taxon candidates and version/near-duplicate proposals with evidence.
