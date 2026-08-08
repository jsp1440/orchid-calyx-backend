# CALYX-465 — Mycorrhizal evidence and fungal relationship pipeline

Status: IMPLEMENTED / GOVERNED REVIEW-ONLY

## Delivered

- Owner-scoped orchid-fungus association records with orchid taxon identity, fungal identity/resolution, tissue, life stage, locality, method, confidence, contradiction, and review state.
- Direct binding to CALYX-448 Literature Intelligence evidence spans by `literature_run_id` + `span_id`; the stored association preserves exact text, span checksum, source/revision identity, source checksum, and extraction checksum.
- Orchid identity reuses the canonical taxonomy `scientific_name`/`taxon_key` contract.
- Fungal resolution remains explicit: one canonical candidate resolves; multiple or absent candidates enter the unresolved queue.
- Verified `mycorrhizal_association` records require an explicit documented-association flag plus bound literature evidence.
- `co_occurrence_only` records cannot be promoted to verified symbiosis; attempts fail closed.
- Low-confidence and contradictory records enter review with explicit reasons.
- Provenance traversal exposes association → exact literature evidence span → literature revision/source.
- Bounded local relationship staging preserves provenance and is replay-idempotent by deterministic record digest.
- Protected Mission Control record, unresolved queue, provenance, stage, and readiness APIs.
- Deterministic fixture tests plus CALYX-448 Literature Intelligence regression coverage.

## Governance boundaries

This slice does not convert co-occurrence into verified symbiosis, autonomously publish scientific conclusions, mutate the production Knowledge Graph, perform live provider/network acquisition, deploy production changes, or authorize merge. Local staging is review-only and explicitly records that no production graph mutation occurred.

## Validation

Dedicated CI compiles the mycorrhizal runtime/router/Mission Control surface, runs CALYX-465 tests plus Literature Intelligence #448 regressions, asserts permanent co-occurrence/non-publication/non-production-mutation boundaries, runs Ruff, and checks diff hygiene. The branch remains draft/unmerged until exact-head validation completes.
