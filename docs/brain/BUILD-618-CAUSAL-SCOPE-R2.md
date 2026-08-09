# BUILD-618-R2 — Causal Applicability Scope

## Status

Reconstructed on `feature/build-618-causal-scope-r2` from the validated BUILD-617-R2 head. Replacement PR #787 supersedes the stale original BUILD-618 stack.

The exact validated code head is `152abdda0fce0188a1b40b30380cd23f018d1456`. Dedicated BUILD-618 run `31301659016` passed compile, Ruff lint/format, causal-scope regressions, BUILD-617/616/615 prerequisite regressions, and hygiene. Applicable broad checks also passed on the same head: BUILD-617, BUILD-616, BUILD-615, Workflow Governance, CALYX Brain E2E, and Calyx Brain Integration.

Executable CI exposed three correctable findings before readiness: one Ruff annotation rule, deterministic formatting drift, and two regression assertions. The first regression assertion was a test-shape error (`source_pk` is serialized under node provenance); the second confirmed that legacy publication-readiness fixtures must now declare bounded scope because BUILD-618 intentionally makes unknown scope publication-blocking. Both were corrected without weakening the new scope gate or the BUILD-616 canonical identity invariant.

## Purpose

A mechanistic relationship is not automatically universal merely because its causal predicate is controlled and its evidence is reviewed. BUILD-618 introduces an explicit applicability-scope contract so absence of scope is represented as `unknown`, never silently promoted to global applicability.

## Scope contract

`CausalScope` supports three scope classes:

- `unknown`: no scientifically justified applicability boundary is asserted;
- `bounded`: at least one explicit taxonomic, anatomical, developmental, environmental, treatment, cultivation, or population boundary is required;
- `global`: explicit global justification is required and local bounds are forbidden.

Normalized scope contains taxa, organs, tissues, cell types, developmental stages, environments, treatments, cultivation context, population context, notes, and global justification. String collections are normalized case-insensitively and deterministically. Each normalized scope receives a deterministic scope ID.

## Candidate integration

Mechanistic candidate requests carry `causal_scope`. The normalized scope is persisted in Candidate Knowledge qualifiers and the read-only graph preview. An omitted scope becomes `unknown`; it is never inferred from unrelated metadata and never treated as global.

## Contradiction integration

BUILD-617 contradiction identity now incorporates normalized causal scope while retaining experimental and quantitative context for compatibility. Opposite-polarity claims from different bounded scopes therefore do not become false contradictions merely because they share canonical endpoints.

Invalid scope is fail-closed and reported as skipped contradiction input rather than silently normalized into a valid scientific scope.

## Publication planning

BUILD-616 publication planning now blocks:

- unknown scope: `causal_scope_unknown`;
- invalid scope: `invalid_causal_scope:<reason>`.

The projected graph preserves normalized scope in node and edge payloads. The BUILD-616 canonical identity correction is retained: projected node `source_pk` is derived from and must remain consistent with `canonical_key`; BUILD-618 does not regress this invariant.

A bounded or explicitly justified global scope can become publication-plan-ready only if all pre-existing evidence, review, contradiction, graph-validation, and governance gates also pass.

## Validation

Focused tests cover unknown-scope blocking, bounded/global validation, deterministic normalization, global/local-bound incompatibility, canonical projected endpoint identity, cross-scope non-contradiction, and same-scope opposite-polarity contradiction.

The dedicated CI workflow also executes BUILD-617, BUILD-616, and BUILD-615 regressions before readiness.

## Governance

BUILD-618 is modeling and read-only planning infrastructure. It does not approve scientific review, resolve contradictions, authorize publication, mutate Candidate Knowledge review state, write the production database, activate taxonomy, deploy code, or mutate the canonical Knowledge Graph.
