# BUILD-618-R3 — Causal applicability scope on canonical main

## Status

**IMPLEMENTED / VALIDATION REQUIRED.** This R3 reconstruction starts directly from canonical backend `main` after BUILD-616R/617R3 and BUILD-BRAIN-114R. Historical PR #787 / R2 is source material only because it is deeply stacked on obsolete ancestry.

## Objective

Make mechanistic causal claims explicit about where they apply. Missing scope is `unknown`, never silently global. Bounded claims require material applicability dimensions. Global claims require explicit justification and cannot carry local bounds.

## Scientific invariants

- `CausalScope` is deterministic and extra fields fail closed.
- Whitespace-only list entries do not count as applicability evidence.
- `bounded` requires at least one material applicability dimension after normalization.
- `global` requires justification and rejects local bounds.
- Candidate Knowledge preserves normalized scope in qualifiers and graph preview.
- Publication readiness blocks unknown or invalid scope and emits no operations while blocked.
- Publication plans retain BUILD-616R review-bound identity, canonical endpoint resolution, candidate provenance, and `publication_adapter_available=false`.
- Contradiction identity uses endpoint identity plus normalized applicability dimensions only.
- Narrative `applicability_notes`, `global_justification`, experimental/quantitative narrative, and derived `scope_id` cannot split an otherwise identical contradiction group.
- Different real bounded applicability dimensions remain distinct and are not conflated.

## P1 review remediation inherited from #787

### Blank bounded scope

R2 checked raw list truthiness before normalization, so `tissues=["   "]` could pass as bounded and later normalize to an empty list. R3 rejects such input at the model boundary and rechecks normalized dimensions defensively.

### Narrative contradiction identity

R2 hashed the entire normalized causal-scope object, including justification/notes/derived scope ID, so opposite-polarity claims could evade contradiction grouping through narrative wording changes. R3 computes a dedicated applicability identity containing only scope class and scientific applicability dimensions.

## Governance

This build does not resolve scientific contradictions, approve Candidate Knowledge, publish scientific knowledge, mutate the canonical Knowledge Graph, activate taxonomy, apply production database migrations, or deploy production services. It only strengthens candidate/reasoning/readiness semantics and remains fail-closed.

## Validation plan

Dedicated BUILD-618 CI compiles and lints the scope/candidate/contradiction/publication surfaces, runs BUILD-618 adversarial regressions plus BUILD-617/616/615 prerequisites, asserts permanent scope-governance invariants, and checks current-main diff hygiene. Applicable broad Brain, publication-readiness, and workflow-governance checks must also pass before merge.
