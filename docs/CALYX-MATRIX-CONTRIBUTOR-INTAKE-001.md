# CALYX-MATRIX-CONTRIBUTOR-INTAKE-001 — Contributor Image Intake & Governed Evidence Pathway

Status: implementation (this PR). Narrowly scoped; no production activation.

## Purpose

Add the missing first mile of Matrix evidence acquisition: a governed intake
path for contributor photographs that feeds the existing, canonical Matrix
identification stack without weakening any governance boundary.

Pipeline:

```
contributor image batch intake
  -> governed Matrix session (registry-bound, owner-scoped)
  -> machine character extraction as review-required suggestions
  -> expert review (accept / revise / reject)
  -> deterministic candidate re-ranking
  -> reuse-before-pay source planning + budget-guarded Firecrawl extraction
  -> source comparison vs existing governed assertions
  -> content-addressed governed Matrix evidence record (unverified)
```

## What this adds

### `runtime/contributor_image_intake.py`
Batch ingestion of contributor submissions. Preserves the original photograph
reference and content SHA-256 (originals are never modified), contributor
attribution and explicit permission grant, rights-holder affirmation, taxonomic
uncertainty (`determined_by_contributor` / `suggested` / `unknown`, plus
candidate taxa), and provenance. Idempotent via content-checksum dedup;
unsupported media and missing permission/attribution are rejected with explicit
reasons. Complements `runtime/image_staging.py` (provider-licensed GBIF /
iNaturalist staging) with the distinct contributor-direct permission model.
No production mutation.

### `runtime/matrix_contributor_bridge.py`
Review-gated bridge into the canonical Matrix session runtime. Machine-extracted
characters attach as `pending_review` / `needs_mapping` suggestions and never
score until a reviewer explicitly accepts (with unambiguous registry mapping)
or revises them. Reviewer certainty is required and is never copied from
machine confidence. Reviewed observations enter scoring through the normal
`add_observation` path with `kind: contributor_image_reviewed` and full
contributor/image/machine provenance. `build_contributor_evidence_record`
freezes image identity + session revision + registry checksum + reviewed
observations + machine audit + candidate ranking + source comparison into a
content-addressed record labeled `unverified_candidate_evidence`; promotion to
verified scientific evidence is a separate governed action, not implemented here.

### `app/federation/morphology_evidence.py`
Extends the shared Firecrawl federation layer (FIRECRAWL-FEDERATION-001, still
map-only in production) toward controlled factual text extraction:
- per-source policy gate (terms reviewed + robots compliant; unknown sources fail closed);
- strict credit budget checked against the shared acquisition ledger before any
  provider call; budget exhaustion blocks new fetches, never cache reads;
- dedup through the same acquisition primitives (`AcquisitionRequest` /
  stable identifiers), so repeat consumers spend zero credits;
- bounded verbatim excerpts only (default 280 chars) — no article cloning, no
  image retrieval;
- every excerpt is `literature_excerpt_unverified`, `review_required`, with
  source URL, attribution, and retrieval timestamp;
- `plan_evidence_acquisition` skips provider calls for characters already
  covered by existing governed evidence (reuse before pay).

Production wiring uses the shared SQLAlchemy `AcquisitionLedger`; an in-memory
ledger is provided for bounded tests and the offline demo.

### `scripts/matrix_contributor_intake_demo.py`
Fully offline end-to-end demonstration (stub extractor, in-memory ledger,
file-backed stores, zero credits, zero network). Run:

```bash
python scripts/matrix_contributor_intake_demo.py --output /tmp/evidence.json
```

## Matrix-ready evidence: documented vs tested vs deployed

Honest inventory as of this change (no coverage claims beyond evidence):

| Capability | Documented | Tested (repo tests) | Deployed/active in production |
|---|---|---|---|
| Deterministic candidate-ranking engine (`runtime/matrix_identification.py`) | yes | yes | candidate-ranking only; not a taxonomic determination service |
| Immutable registry versions (file + PG stores) | yes | yes (file-backed) | PG migration 613 NOT applied; durable registry NOT enabled |
| Governed sessions / next-best observation | yes | yes (file-backed) | PG migration 612 NOT applied; durable sessions NOT enabled |
| Vision → Matrix review gate | yes | yes | live Vision provider inference NOT activated |
| Reproducible evidence reports | yes | yes | code canonical; CI execution blocked by GitHub Actions billing |
| KG-backed source assertions (`matrix_relationship_sources.py`) | yes | yes (read-only adapters) | depends on governed source registry rows; per-dimension |
| Firecrawl federation | yes | yes (mocked network) | map-only reconnaissance; no production crawl authorized |
| Contributor image intake (this PR) | yes | yes (this PR) | NO — code only, no route wiring, no deployment |
| Firecrawl morphology extraction (this PR) | yes | yes (stubbed extractor) | NO — no paid extraction authorized |
| ~30,000-species character coverage | — | — | NO EVIDENCE. No committed registry packages exist; registries are runtime-created evidence packages. Species coverage must not be claimed until registry versions with candidate data actually exist. |

## Governance boundaries (unchanged, still active)

- No AI-inferred character becomes scored Matrix evidence without explicit review.
- Reviewer certainty is never copied from machine confidence.
- Unknown observations score zero; missing candidate state reduces coverage and
  is never treated as biological absence.
- No canonical taxonomy mutation, no KG auto-publication, no automatic
  identification publication.
- No robots.txt/terms bypass; unknown sources fail closed; paid crawling
  requires separate authorization.
- This PR merges no migration, enables no durable flag, and spends no credits.

## Tests

- `tests/test_contributor_image_intake.py` — 10 tests (AC-1).
- `tests/test_matrix_contributor_bridge.py` — 6 tests (AC-2).
- `tests/test_morphology_evidence.py` — 7 tests (AC-3).
- Offline harness additionally re-ran `tests/test_matrix_identification_session_001.py`
  (6 upstream regression tests) — all pass. 29 tests + demo, exit code 0.

## Next integration action (proposed, not done here)

Wire `POST /api/matrix-contributor/intake` + suggestion review routes into
`app/routers/`, persisting staged images and sessions via the governed stores,
behind authentication — as its own reviewed PR.
