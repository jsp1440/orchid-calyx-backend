# BUILD-621-R3 — Plant Diagnostic Context Composer

## FACT

- Canonical parent at reconstruction start: BUILD-620-R4 merged to `main` as `27f5f912d0ebc09d0fa4ee996b0e07b56e6900c7`.
- Historical BUILD-621-R2 PR #790 is stale stacked ancestry and is source material only.
- This R3 branch is rebuilt directly on current canonical `main`.

## IMPLEMENTED

- Added `PlantDiagnosticContextRequest` and read-only `compose_plant_diagnostic_context()`.
- Added protected `POST /brain/diagnostic-context` under the existing authenticated Brain router.
- Composes two explicitly separate channels:
  1. canonical scoped Reasoning Map results;
  2. plant-scoped local observation history from canonical Candidate Knowledge storage.
- Local observations are never inserted into the canonical graph and never treated as proof of a canonical mechanism.
- Unknown or out-of-scope canonical pathways retain BUILD-619 fail-closed applicability semantics.
- Whitespace-only plant-record identity is rejected at the request boundary.

## GOVERNANCE

- `read_only=true`.
- `canonical_graph_mutated=false`.
- `candidate_knowledge_mutated=false`.
- `local_observation_implies_canonical_mechanism=false`.
- `automatic_scientific_claim_generation=false`.
- `automatic_publication=false`.
- `scientific_publication_authority=false`.
- Human review remains required for any new scientific claim.

## VALIDATION PLAN

Dedicated BUILD-621 validation must execute on the exact release head and include:

- compile;
- Ruff lint and formatting;
- BUILD-621 focused diagnostic-context regressions;
- BUILD-620 local observation regressions;
- BUILD-619 reasoning-scope regressions;
- BUILD-618 causal-scope regressions;
- protected route import/assertion;
- permanent non-authority assertions;
- diff hygiene.

Broad backend integration, Brain E2E, BUILD-088E, and Workflow Governance checks remain release requirements when triggered.

## BLOCKED / NOT AUTHORIZED

No scientific diagnosis is asserted by this composer. No scientific review decision, contradiction resolution, Candidate Knowledge promotion, scientific publication, taxonomy activation, production database mutation, production Knowledge Graph mutation, deployment, or production write authority is introduced.
