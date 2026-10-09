# CALYX MATRIX — CONTRIBUTOR LIVE INTAKE (Phase 2)

Continues `CALYX-MATRIX-CONTRIBUTOR-INTAKE-001.md` (PR #1793,
`calyx-matrix-contributor-intake-001`). Phase 1 delivered the offline intake
governance module, review-gated Matrix bridge, and an offline demo. Phase 2 puts
that pathway behind the authenticated HTTP API, adds durable governed
persistence for batches, and proves the whole flow over real API requests.

Nothing from Phase 1 is rebuilt; the new code composes the existing
`contributor_image_intake` / `matrix_contributor_bridge` /
`matrix_identification_session` modules.

## What was added

| File | Role |
| --- | --- |
| `runtime/contributor_intake_service.py` | Governed durable-intake service: content-addressed originals, checksum index, atomic batch manifests, two-level idempotency, optional session opening. |
| `app/routers/matrix_contributor.py` | Authenticated FastAPI router (`/api/matrix-contributor/...`). |
| `app/routers/reference_docs.py` | 2-line wiring: import + `include_router` (existing nesting pattern). |
| `runtime/matrix_contributor_bridge.py` | Adds read-only `list_contributor_suggestions` (owner-scoped, optional state filter). |
| `scripts/matrix_contributor_api_demo.py` | Live demo: boots uvicorn, drives the full flow with httpx. |
| `tests/test_matrix_contributor_api.py` | API, auth, persistence, idempotency, review-gate, tenant-scoping tests. |
| `tests/test_contributor_intake_service.py` | Service-level persistence / checksum / dedup / mapping tests. |
| `tests/test_matrix_migration_contract.py` | Static reconciliation of migrations 612/613 against the preflight and registry-store contracts. |

## API surface

All routes require `verify_owner_or_api_key` (X-API-Key automation or signed
owner session). Error mapping follows the existing convention:
`FileNotFoundError → 404`, `ValueError → 422`, `RuntimeError → 503`.

| Method & path | Purpose |
| --- | --- |
| `POST /api/matrix-contributor/intake` | Batch intake of contributor photographs (base64 content + metadata). |
| `GET /api/matrix-contributor/batches/{batch_id}` | Fetch a persisted batch manifest (idempotent-replay visible). |
| `POST /api/matrix-contributor/sessions/{session_id}/extractions` | Attach contributor character extractions to a staged image. |
| `GET /api/matrix-contributor/sessions/{session_id}/suggestions` | List suggestions (optional `state` filter). |
| `POST /api/matrix-contributor/sessions/{session_id}/suggestions/{suggestion_id}/review` | Review-gate decision: accept / revise / reject (single decision; second → 422). |
| `POST /api/matrix-contributor/sessions/{session_id}/evaluate` | Run Matrix scoring over accepted observations. |
| `POST /api/matrix-contributor/sessions/{session_id}/evidence-record` | Build a contributor evidence record (`unverified_candidate_evidence`). |

### Intake request notes
- `submissions`: 1–500 items. Each carries `original_filename`,
  `content_base64`, optional client `content_sha256` (cross-check only — the
  server computes its own SHA-256 and rejects mismatches), optional
  `original_object_ref`, `mime_type`, permission/rights flags, and taxon hints
  (`taxon_name`, `taxon_certainty`, `candidate_taxa`, `provenance`).
- `contributor_id` in a submission is honored **only** for the trusted API-key
  automation channel; owner sessions always get their own identity.
- `open_sessions=true` opens one Matrix session per staged image.
- `batch_id` may be supplied by the caller for idempotent replay.

### Response mapping
The manifest `filename_mapping` maps every original filename to its outcome:
`staged` (with submission id, checksum, object ref, resolved taxon candidate,
and `session_id` when opened), `rejected` (with reasons), or
`duplicate_skipped` (checksum seen before — cross-batch).

## Persistence & governance

- **Originals** are stored content-addressed:
  `originals/{sha256[:2]}/{sha256}{suffix}`. Writes are create-only; a checksum
  conflict raises `CONTRIBUTOR_ORIGINAL_CHECKSUM_CONFLICT`. The original bytes
  are never mutated, matching the governed-storage posture of the existing
  file-backed session/registry stores.
- **Checksum index** (`index/checksums.json`) and **batch manifests**
  (`batches/{batch_id}.json`) are written atomically (tmp file + `os.replace`).
- **Root** resolves at call time from `CALYX_MATRIX_CONTRIBUTOR_INTAKE_DIR`
  (default `/tmp/calyx/matrix-contributor-intake`).
- **Sessions, review decisions, and provenance** persist through the existing
  `FileMatrixSessionStore` / `PostgresMatrixSessionStore` (migration 612 when
  durable mode is activated). Session metadata links
  `contributor_submission_id`, `contributor_batch_id`, `content_sha256`, and
  `original_object_ref` back to the intake records.
- **Idempotency**: Level 1 — replaying an existing `batch_id` returns the
  stored manifest with `idempotent_replay=true` and opens no new sessions.
  Level 2 — the checksum index skips re-submitted content across batches.

## Review gate → scoring

Attached extractions start as suggestions in `pending_review`. `evaluate`
ignores them (`observation_count == 0`) until a review decision accepts or
revises them; only then do they enter scoring and shift candidate rankings.
Rejecting excludes them permanently. Each suggestion accepts exactly one
decision. `evidence-record` marks the result `unverified_candidate_evidence`
with `source.kind == "contributor_image_reviewed"` — contributor-derived
evidence is never presented as verified.

## Migration reconciliation (612/613)

The migrations were verified **statically** against the runtime contracts they
must satisfy — no migration is applied anywhere by this change (merging a
migration has never applied it; production application remains a separately
authorized operation):

- 612 `matrix_identification_sessions`: every column, type, and default
  required by `runtime/matrix_identification_persistence_preflight.py`
  (`REQUIRED_COLUMNS`), the primary key, the `revision` CHECK, and the exact
  three index column tuples (`REQUIRED_INDEX_COLUMNS`) are asserted.
- 613 `matrix_identification_registry_versions`: asserted against
  `runtime/matrix_identification_registry_store.py` (`REQUIRED_COLUMNS`,
  `REQUIRED_INDEXES`).
- Governance-boundary flags (`CALYX_MATRIX_SESSION_DURABLE_ENABLED`,
  `CALYX_MATRIX_REGISTRY_DURABLE_ENABLED`) must remain documented in the
  migration comments; both files must be transactional (BEGIN/COMMIT).
- `assess_matrix_session_schema` accepts a snapshot built from the 612
  contract and rejects a drifted snapshot.

No new migration is introduced: the intake pathway's own persistence is
file-backed (content-addressed originals + atomic JSON manifests), and
session-scoped records reuse 612's table.

## Verification

`python3 verifier/run_verifier.py` (criteria: `verifier/v2/acceptance_criteria.md`):

- 51 tests passed, 0 failed — v1 suites intact plus 22 new tests covering
  auth (401 boundaries), intake persistence, idempotent replay across a
  simulated restart, review-gated scoring through the API, owner tenant
  scoping, service-level checksum/dedup/mapping, and migration contracts.
- `scripts/matrix_contributor_intake_demo.py` — Phase 1 offline demo, PASS.
- `scripts/matrix_contributor_api_demo.py` — live uvicorn demo over HTTP:
  auth boundary (401) → batch intake (2 photos, sessions opened) → extraction
  attach (pending, invisible to scoring) → review accept/revise → evaluate
  (leader hypothesis) → evidence record → batch replay idempotency. PASS.

Run record: `verifier/runs/20261009T153105Z.log` (`exit_code=0`).

## Boundaries

- No deployment, no merge, no billable services, no crawls.
- Migrations verified, not applied.
- PR opened as **draft** for integration review, scoped to the files above;
  Phase 1 files are untouched except the 2-line router wiring and the additive
  bridge function.
