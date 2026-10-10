# CALYX Matrix — Identification Workflow (Phase 3, capability 003)

Status: implemented and locally verified; **not deployed**. DRAFT PR stacked on
Phase 2 (`calyx-matrix-contributor-live-intake-002`, PR #1794), which is stacked
on Phase 1 (`calyx-matrix-contributor-intake-001`, PR #1793). No merges, no
production deployment, no migrations, no paid providers.

## What exists now (documented + tested)

**Identification report builder** — `runtime/matrix_identification_workflow.py`
`build_identification_report(session_id, ...)` loads a governed Matrix session
and its bound registry, runs the existing Matrix engine (`evaluate_session`),
and emits a content-addressed report (`matrix-identification-report/v1`):

- Candidate taxa ranked by the existing certainty-factor engine, with score and
  coverage kept separate (coverage is character coverage, not confidence).
- Per-candidate character evidence classified as **supporting**, **partial**,
  **contradicting**, **candidate-state-missing** (explicitly *not* evidence of
  biological absence), and **unknown observations** (preserved, never dropped).
- Every character row links back to its source observation with full provenance:
  reviewer, review decision, contributor submission id, content SHA-256,
  original object reference, attribution line, and permission grant.
- **Taxonomic resolution** (`runtime/matrix_taxon_resolution.py`): exact
  normalized matching only (case/whitespace-insensitive; *no fuzzy matching* —
  a near-miss stays unresolved and is reported as a limitation). Governed
  synonym entries take precedence over candidate self-registration. Resolution
  is a reporting reconciliation, never a taxonomy mutation. Candidates that
  resolve to the same canonical taxon are grouped with all members preserved.
- **Uncertainty and limitations**: ambiguity detection (all leaders within
  epsilon of the top score are reported as an indistinguishable group, never a
  silent single winner), unobserved-character listing, review-gate accounting
  (pending / needs-mapping / rejected suggestions are counted and excluded from
  scoring), and dynamic limitations (zero-observation sessions report "no
  evidential weight"; unresolved names and collapsed synonym groups are
  surfaced).
- **Determinism and durability**: the report checksum is SHA-256 over the
  canonical JSON payload with `created_at` outside the checksum, so repeat
  requests are byte-identical and reports regenerate identically after restart
  from governed session storage.

**API** — `POST /api/matrix-contributor/sessions/{session_id}/identification`
on the existing contributor router. Same auth as Phase 2: `X-API-Key` for
trusted automation, owner Bearer tokens tenant-scoped (cross-owner access is
404, fail-closed). Body: `limit`, `ambiguity_epsilon`, optional
`synonym_entries` (governed reconciliation data), optional `source_assertions`
for governed-source comparison.

## Automated vs human stages (honest boundary)

| Stage | Automation |
|---|---|
| Contributor image intake (hashing, dedup, governed storage) | Automated |
| Character extraction from images | Automated **only when an authorized extractor is configured**. No vision model is wired in Phase 3; the demo uses a deterministic fixture extractor explicitly labeled as a stand-in, plus a manual contributor fallback. **Image-based identification is never claimed from contributor-supplied labels.** |
| Expert review (accept / revise / reject) | **Human.** Unreviewed machine suggestions never become scored evidence. |
| Candidate scoring | Automated (existing Matrix engine) |
| Identification report (evidence, synonyms, ambiguity, limitations) | Automated |
| Taxonomic determination | **None.** The report is explicitly not a taxonomic determination. |

## Tests (20 new; 71 total green)

- `tests/test_matrix_taxon_resolution.py` — canonical/synonym resolution,
  no-fuzzy guarantee, normalization, precedence, collapse.
- `tests/test_matrix_identification_workflow.py` — evidence classification,
  ambiguity tie, unobserved characters, review-gate exclusion, provenance
  links, synonym collapse without deletion, unresolved-name limitation,
  zero-observation honesty, checksum determinism, restart persistence.
- `tests/test_matrix_identification_api.py` — 401 unauthenticated, full report
  over HTTP with idempotent checksum, cross-owner 404, restart persistence.

## Live demonstration

`scripts/matrix_identification_workflow_demo.py` boots a real uvicorn server
(loopback only) and drives the full pathway end to end with stage labels and
11 checks, including repeat-request idempotency and post-restart persistence.
Verifier: `python3 verifier/run_verifier.py` → 71 passed, 0 failed, all three
demos pass (`verifier/runs/20261010T051956Z.log`).

## Deployment prerequisites (owner authorization required)

1. Merge order: PR #1793 → PR #1794 → this PR (stacked).
2. Migrations 612/613 are **verified by contract tests only**; applying them to
   production requires explicit owner authorization.
3. A real vision/extraction model is **not** integrated. Wiring one requires an
   authorized, deterministic extractor plus the same review gate — machine
   output must remain pending until human review.
4. No paid providers were used or configured; keep it that way absent owner
   authorization and a budget guard.
