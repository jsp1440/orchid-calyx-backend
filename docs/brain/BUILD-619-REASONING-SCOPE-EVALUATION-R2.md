# BUILD-619-R2 — Scope-Aware Reasoning Map Evaluation

## Status

Reconstructed on `feature/build-619-reasoning-scope-evaluation-r2` directly from the executable-green BUILD-618-R2 chain. Replacement PR #788 supersedes the stale original BUILD-619 stack.

The exact executable-green code head is `54c282199c7d38f43861c1270a8be070426be7e3`. Dedicated BUILD-619 run `31301980652` passed compile, Ruff lint/format, scoped reasoning regressions, BUILD-618 causal-scope regressions, BUILD-612 reasoning-map regressions, scoped-route verification, and hygiene. Applicable broad checks also passed on the same head: Workflow Governance, Canonical Brain, CALYX Agent 001/003/004, CALYX Core Rebase, Journalism MVP, Education Design, Calyx Brain Integration, and CALYX Brain End-to-End Certification.

Executable CI exposed three correctable integration findings before readiness: an import-format issue, a single test formatting drift, and a missing `httpx` test dependency required by the inherited BUILD-612 FastAPI TestClient regression suite. All were corrected before accepting behavioral validation; no scientific or governance gate was weakened.

## Purpose

BUILD-618 established that causal applicability must be explicit and that unknown scope is never equivalent to global scope. BUILD-619 carries that contract into explanatory reasoning maps.

The existing deterministic Reasoning Map engine remains the source of graph traversal. BUILD-619 does not change traversal semantics or manufacture new causal edges. Instead it evaluates every returned causal edge and pathway against an explicit query applicability scope.

## Applicability states

Each evaluated edge or pathway is classified as one of:

- `applicable`: all claim dimensions that require comparison are compatible with the query scope;
- `out_of_scope`: at least one bounded claim dimension conflicts with the query scope;
- `indeterminate`: applicability cannot be established because the claim scope is unknown or the query omits a required claim dimension;
- `not_evaluated`: no query scope was supplied to a lower-level evaluator.

The protected scoped reasoning endpoint requires an explicit applicability scope, so user-facing scoped maps are evaluated rather than silently defaulted.

## Matching rules

For list-valued dimensions such as taxon, organ, tissue, cell type, and developmental stage, a bounded claim matches when the claim and query sets intersect. A required claim dimension absent from the query is indeterminate, not a match.

For structured dimensions such as environment, treatment, cultivation context, and population context, shared keys must agree. Conflicting shared values are out of scope; no shared keys are indeterminate.

An explicitly justified global claim is applicable to a bounded query. An unknown claim scope is always indeterminate.

## Reasoning map integration

`POST /brain/reasoning-map/scoped` uses the existing authenticated Brain router and returns the normal deterministic reasoning-map structure plus:

- edge-level applicability evaluations;
- path-level applicability evaluations;
- counts of applicable, out-of-scope, and indeterminate paths;
- the normalized query applicability scope;
- `safe_to_generalize`.

Out-of-scope pathways are retained in the response for transparency instead of being silently removed.

`safe_to_generalize` is deliberately conservative. It is true only when the map contains at least one path and every path is applicable, with no out-of-scope or indeterminate paths. An empty map is never safe to generalize.

## Governance

BUILD-619 is read-only explanatory reasoning. It does not:

- prove causality;
- infer global applicability from missing scope;
- alter traversal to hide conflicting or out-of-scope evidence;
- resolve mechanistic contradictions;
- approve or publish Candidate Knowledge;
- mutate the canonical Knowledge Graph;
- write the production database or deploy code.

## Validation

Focused regressions cover matching and mismatching bounded scopes, indeterminate structured dimensions, unknown claim scope, explicit global scope, transparent retention of out-of-scope pathways, and the empty-map generalization guard.

The dedicated workflow also runs BUILD-618 causal-scope regressions and the existing BUILD-612 reasoning-map regressions, verifies the protected scoped route, performs lint/format/compile checks, and requires a clean repository state.
