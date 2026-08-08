# CALYX-466 — Conservation evidence, threats, and protection-status pipeline

Status: IMPLEMENTED / GOVERNED REVIEW-ONLY

## Delivered

- Owner-scoped conservation assessment records with canonical taxon identity, source authority, assessment version/date, category system/category, population/trend, threats, protected areas, actions, confidence, conflicts, freshness, and review state.
- Exact CALYX-448 Literature Intelligence evidence binding by run/span with source/revision/extraction checksums.
- Occurrence-evidence and Atlas-feature reference contracts are preserved explicitly for downstream reconciliation without inventing occurrence or protected-area facts.
- IUCN-labelled category records fail closed unless the stated source authority is IUCN (or its full organization name); the service does not invent IUCN status.
- Deterministic assessment freshness and stale-assessment detection with a configurable age threshold and recorded `as_of` date.
- Stale, conflicting, low-confidence, or threat-incomplete assessments enter the review queue with explicit reasons.
- Bounded local assessment staging is replay-idempotent by deterministic record digest and records no production graph mutation or scientific publication.
- Protected Mission Control record, review-queue, stage, and readiness APIs.
- Deterministic fixture tests plus CALYX-448 Literature Intelligence regression coverage.

## Governance boundaries

This slice does not fabricate IUCN status, autonomously publish conservation conclusions, mutate production Knowledge Graph data, perform live provider acquisition, deploy production changes, or authorize merge. Occurrence and Atlas IDs are references only and are never treated as evidence unless supplied by their governed upstream systems.

## Validation

Dedicated CI compiles the conservation runtime/router/Mission Control surface, runs CALYX-466 tests plus Literature Intelligence #448 regressions, asserts permanent no-fabrication/non-publication/non-production-mutation boundaries, runs Ruff, and checks diff hygiene. The branch remains draft/unmerged until exact-head validation completes.
