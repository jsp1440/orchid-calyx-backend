# BUILD-087B — Context-Preserving Scientific Evidence Interpretation Implementation Report

## Verdict

**READY — BUILD-087 IMPLEMENTATION COMPLETE**

## Baseline

- Base branch: `main`
- Verified base commit: `a8a1eff12c7974c4fa4d8d75234d66d5b78a37a5`
- Architecture reference: approved BUILD-087A context-preserving evidence architecture

## Components implemented

- Immutable Layer 1 source-evidence references with exact ordered anchors, locators, content hashes, publication metadata, provenance, and copyright policy.
- Versioned Evidence Packets for paragraphs, linked sentences, tables with headers, figures with captions, methods/results, taxonomic treatments, and other semantically complete contexts.
- Explicit completeness states for every scientific context dimension, including taxa, anatomical structures, traits, measurements, units, life stage, population/sample, geography, time, methods, experimental/environmental conditions, qualifiers, negation, comparisons, citations, and biological context.
- Reproducible Layer 2 machine interpretations with packet fingerprints, model/ruleset/vocabulary versions, configuration hashes, reasoning, decomposed confidence, ambiguities, alternatives, and supersession lineage.
- Versioned, derived Layer 3 canonical assertions with scientific scope, supporting/conflicting interpretations, persisted routing decisions, publication eligibility, and an invariant `published=false`.
- Versioned routing policies and objective Automatic Promotion, Provisional Scientific Assertion, and Exception Review decisions. Hard scientific gates cannot be offset by a composite score.
- Structured reviewer corrections that append a corrected interpretation version and retain the original interpretation unchanged.
- Append-only audit history for every persisted artifact and service action.
- Authenticated backend endpoints for packet construction, interpretation, policy evaluation, assertion creation, correction capture, audit history, and health. There is no publication endpoint.
- Additive PostgreSQL persistence with independent artifact tables, deterministic fingerprints, logical version keys, concurrency serialization, indexes, audit triggers, and database-level rejection of updates/deletes.

## Files changed

- `.github/workflows/build-087b-validation.yml`
- `app/main.py`
- `app/scientific_interpretation/__init__.py`
- `app/scientific_interpretation/models.py`
- `app/scientific_interpretation/repository.py`
- `app/scientific_interpretation/postgres_repository.py`
- `app/scientific_interpretation/routes.py`
- `app/scientific_interpretation/service.py`
- `migrations/087b_context_preserving_interpretation.sql`
- `tests/test_build_087b_scientific_interpretation.py`
- `docs/BUILD-087B-IMPLEMENTATION-REPORT.md`

## Architecture compliance

- The three layers have separate identities and histories; no layer overwrites another.
- Source wording is not normalized or rewritten. Packets retain immutable references to context in the existing evidence system.
- Detached fragments are not accepted as a packet form. Linked/table/figure/method contexts require their structural relationships.
- Material ambiguity or unknown context creates an incomplete packet and blocks interpretation.
- Interpretations are idempotent for identical immutable inputs and versioned for changed inputs.
- Routing decisions are persisted and idempotent. Assertions cannot accept a caller-fabricated decision and must be supported by the decision's interpretation.
- Copyright, provenance, context, taxonomy, measurement, contradiction, alternative-interpretation, impact, model, health, and confidence gates are explicit and explainable.
- Corrections create new interpretation and correction versions; historical artifacts are recoverable.
- PostgreSQL triggers make all scientific artifacts and audit events append-only.
- No Knowledge Graph, taxonomy, publication, Google Drive, BUILD-082–086 persistence, or protected schema is modified.

## Validation results

Local Windows validation:

- BUILD-087B focused: **17 passed, 1 PostgreSQL-only skipped, 0 failed**
- BUILD-082 through BUILD-087 regression: **105 passed, 3 environment-dependent skipped, 0 failed**
- Full backend: **700 passed, 20 skipped, 1 failed**
- The sole full-suite failure is the pre-existing Windows-only BUILD-085 subprocess-environment test. It launches a child process with only `PYTHONPATH`, preventing the Windows runtime from loading; BUILD-087B does not touch that test or its code path.
- Ruff lint for all BUILD-087B Python: **passed**
- Compile checks: **passed**
- `git diff --check`: **passed**

The Draft PR workflow runs focused tests against disposable PostgreSQL 16, the BUILD-082–087 regression matrix, the full backend suite on Linux, lint, compile, and diff checks. Its results are the authoritative cross-platform validation for the PostgreSQL-only and Windows-only cases.

## Performance observations

The deterministic in-memory foundation constructed 1,000 fully contextual packets in 0.14 seconds during the measured focused run (the enforced ceiling is 5 seconds). PostgreSQL persistence uses append-only single-artifact writes, indexed fingerprints and logical version keys, and transaction-scoped advisory serialization by artifact identity. It does not use whole-repository snapshots, so work and memory remain bounded by the current artifact rather than total corpus size.

## Known limitations

- BUILD-087B is a backend foundation; user interfaces, reviewer authentication design, dashboards, queue workers, consensus review, immediate retraining, and Knowledge Graph publication remain intentionally out of scope.
- Model quality and policy calibration require representative adjudicated scientific corpora in later validation builds. Confidence remains an explainable routing factor, not a truth probability.
- Local PostgreSQL was not configured; the dedicated Draft PR workflow supplies disposable PostgreSQL 16 and validates migration idempotency, persistence reconstruction, auditability, and mutation rejection.
