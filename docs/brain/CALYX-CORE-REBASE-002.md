# CALYX-CORE-REBASE-002 — Current-main ingestion recovery

## Purpose

Recover the still-missing additive functionality from stale PR #399 onto current `main` without reviving its ~135-commit-old base or copying stale route state.

## Implemented

- `runtime/occurrence_staging.py`
  - bounded GBIF/iNaturalist occurrence staging;
  - canonical taxon reconciliation;
  - explicit unresolved-taxon review queue;
  - checksum idempotency and resumable batch checkpoint metadata;
  - no production Knowledge Graph mutation.
- `runtime/image_staging.py`
  - bounded GBIF/iNaturalist media staging;
  - Creative Commons allowlist enforcement before staging;
  - explicit rejection records rather than silent drops;
  - canonical taxon reconciliation and review queue;
  - checksum idempotency;
  - no production Knowledge Graph mutation.
- `runtime/literature_staging.py`
  - bounded literature staging;
  - canonical taxon reconciliation;
  - evidence-span and extraction-manifest preservation;
  - source-text content hashing;
  - explicit unresolved-taxon review queue;
  - candidate-knowledge governance remains intact;
  - no publication or graph mutation.
- `runtime/calyx_core_certification.py`
  - read-only certification contract `calyx-core-certification-v2`;
  - current module import/readiness checks;
  - configuration-presence reporting without secret values;
  - taxonomy, literature, occurrence, and image pipeline status;
  - Reasoning Ledger gate and publication-safeguard reporting;
  - automatic publication remains false.
- Existing `app.routers.calyx_core.router` now mounts the owner-protected endpoint:
  - `GET /api/mission-control/calyx-core/certification`

## Validation contract

Focused tests must demonstrate:

1. occurrence reconciliation, unresolved review handling, and idempotent replay;
2. image license allowlist enforcement before staging;
3. literature evidence-span/content-hash/provenance preservation;
4. certification is read-only and reports current pipeline modules;
5. certification endpoint invokes owner authentication and is actually present on the already-mounted Calyx Core router;
6. compile, Ruff, and `git diff --check` pass for the new slice.

## Relationship to stale PR #399

PR #399 remains source material only. This build intentionally does not merge it directly and does not copy its stale `app/main.py`. The recovered logic is rebuilt against current-main routing.

## Governance

This build grants no production deployment, taxonomy activation, automatic publication, credential disclosure, or production Knowledge Graph mutation. Staging outputs remain candidate/review material until existing governance gates authorize downstream actions.
