# BUILD-618 — Causal Applicability Scope

## Status

Implemented on `feature/build-618-causal-scope`, stacked on BUILD-617. This branch must not merge before BUILD-615/616/617 prerequisites are validation-cleared and repository CI is executable.

## Purpose

A mechanistic claim is not scientifically meaningful without knowing where it applies. BUILD-618 adds a normalized scope contract so an observation made in one taxon, tissue, developmental stage, treatment, or environment cannot silently become a general biological rule.

## Scope classes

- `unknown` — evidence bounds are not yet explicit. This never means global and blocks publication planning.
- `bounded` — one or more explicit applicability bounds are present.
- `global` — the claim is intentionally asserted to apply generally and requires an explicit justification. Global scope cannot simultaneously carry local bounds.

## Supported applicability dimensions

- taxa
- organs
- tissues
- cell types
- developmental stages
- environment
- treatment / dose context
- cultivation context
- population context
- applicability notes

The normalized contract receives a deterministic `scope_id`. String lists are case-folded, de-duplicated, and sorted so semantically identical scopes compare identically.

## Integration

### Candidate Knowledge

`MechanisticCandidateRequest` now accepts `causal_scope`. The normalized scope is preserved in Candidate Knowledge qualifiers and in the graph-preview edge payload. Missing scope defaults to `unknown`, not `global`.

### Contradiction accounting

BUILD-617 contradiction grouping now compares the normalized causal scope together with the source/target graph identity and legacy experimental/quantitative context. Opposite-polarity claims are contradictions only when they occupy the same scientific scope.

Example:

- `cool nights -> inhibits respiration` in root tissue
- `cool nights -> promotes respiration` in leaf tissue

These are not automatically contradictory.

The same two relationships in the same normalized leaf/taxon/treatment scope are contradiction candidates and remain publication-blocking.

### Publication planning

BUILD-616 now blocks publication-plan readiness when scope is `unknown` or invalid. A reviewed claim must therefore have explicit applicability boundaries, or an explicitly justified global scope, before it can reach the controlled publication gate.

Projected graph node/edge payloads preserve the scope object and scope identifier.

## Governance boundaries

BUILD-618 does not:

- infer that a local experiment is globally applicable;
- upgrade `unknown` scope to `global`;
- resolve contradictions;
- approve scientific review;
- authorize publication;
- mutate production `oc_graph`.

Global applicability remains a scientific assertion requiring evidence and explicit justification.

## Validation

`tests/test_build_618_causal_scope.py` covers:

- unknown scope never becoming global;
- unknown scope blocking publication readiness;
- bounded scope requiring real bounds;
- global scope requiring justification;
- deterministic normalization independent of list ordering/case;
- different tissues preventing false contradiction grouping;
- same normalized scope allowing opposite-polarity contradiction detection.

Inherited BUILD-616 publication tests were tightened to use an explicit bounded scope for the publishable-path case.

A dedicated BUILD-618 Actions workflow runs compile, Ruff, formatting, BUILD-615/616/617/618 regressions, and hygiene. Repository hosted-runner issue #481 remains an external validation blocker until jobs execute actual steps.

## Next dependency

The next highest-value layer is reasoning-map scope evaluation: when a pathway combines multiple causal edges, compute the intersection of their applicability scopes and mark a pathway unsupported when the user's taxon/tissue/environment falls outside that intersection. That work should remain stacked until the current CI infrastructure blocker is resolved.
