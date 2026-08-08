# CALYX-464 — Pollinator and ecological interaction evidence pipeline

Status: IMPLEMENTED / GOVERNED REVIEW-ONLY

## Delivered

- Owner-scoped ecological interaction records with canonical subject taxon identity, interaction type, organism identity, locality/date, confidence, contradiction state, review status, and deterministic record digest.
- Exact evidence-span contract preserving source ID, source URL, exact text, locator, retrieval time, and evidence ID.
- Reuse of the taxonomy preflight `scientific_name` and `taxon_key` identity contract rather than a competing taxon identifier scheme.
- Explicit organism reconciliation state: one supplied canonical candidate can resolve; multiple candidates enter ambiguity review; absent candidates remain unresolved for review.
- Pollination claims fail closed unless `pollination_documented=true` accompanies an exact source evidence span. The service does not infer pollination from flower visitation.
- Low-confidence and contradictory evidence enter the review queue with explicit reasons.
- Bounded local relationship staging with replay idempotency by immutable record digest and preserved evidence/provenance.
- Protected Mission Control record, review-queue, stage, and readiness APIs.
- Deterministic fixture tests covering documented pollination, undocumented-pollination rejection, ambiguous organism review, contradiction/low-confidence handling, incomplete evidence rejection, bounded idempotent staging, readiness governance, and authenticated API round trip.

## Governance boundaries

This slice does not infer undocumented pollination, publish scientific conclusions, activate taxonomy, mutate the production Knowledge Graph, perform live provider harvesting, deploy production changes, or authorize merge. Staging is local/review-only and explicitly reports that no production graph mutation occurred.

## Validation

Dedicated CI compiles the interaction runtime/router/Mission Control surface, runs CALYX-464 tests plus taxonomy-release regression coverage, asserts permanent evidence/non-publication/non-production-mutation boundaries, runs Ruff, and checks diff hygiene. The branch remains draft/unmerged until exact-head validation completes.
