# BUILD-619 — Scope-Aware Reasoning Map Evaluation

## Status

Implemented on `feature/build-619-reasoning-scope-evaluation`, stacked on BUILD-618. This work must not merge before the BUILD-615→618 prerequisite stack is validation-cleared and GitHub hosted-runner issue #481 is resolved.

## Purpose

BUILD-619 makes the Reasoning Map answer a second question in addition to “is there a causal pathway?”:

> Does this pathway apply to the taxon, tissue, developmental stage, treatment, environment, or cultivation context being asked about?

The existing deterministic reasoning traversal remains unchanged. BUILD-619 wraps it with applicability evaluation so scope analysis cannot alter canonical graph traversal or hide inconvenient edges.

## Endpoint

Protected Brain endpoint:

`POST /brain/reasoning-map/scoped`

The request includes the standard reasoning-map traversal settings plus an explicit `applicability_scope` using the BUILD-618 causal scope contract.

## Applicability statuses

Each causal edge and each returned path is annotated as:

- `applicable` — every claim-bound dimension supplied by the evidence is compatible with the query context;
- `out_of_scope` — at least one explicit claim bound conflicts with the requested context;
- `indeterminate` — the claim scope is unknown or the query lacks information needed to test a claim bound;
- `not_evaluated` — used only by lower-level helpers when no query scope is supplied.

Unknown scope is never treated as applicable.

## Conservative comparison

For categorical dimensions such as taxon, organ, tissue, cell type, and developmental stage, applicability requires overlap with the claim’s declared bound.

For mapping dimensions such as environment, treatment, cultivation context, and population context:

- a shared key with a conflicting value is out of scope;
- shared compatible keys are matched;
- no shared key is indeterminate, not a match.

This prevents a temperature-bounded study from being treated as applicable merely because the query supplied humidity information.

## Path evaluation

A pathway is:

- out of scope if any constituent edge is out of scope;
- indeterminate if none is out of scope but at least one is indeterminate;
- applicable only when every edge is applicable.

Out-of-scope paths are retained in the result for transparency rather than deleted. The response includes counts of applicable, out-of-scope, and indeterminate paths plus a conservative `safe_to_generalize` flag.

## Governance

BUILD-619 is read-only and explanatory. It does not:

- prove causality;
- infer missing scientific scope;
- upgrade unknown scope to global;
- hide contradictory/out-of-scope evidence;
- publish Candidate Knowledge;
- mutate `oc_graph`.

## Validation

`tests/test_build_619_reasoning_scope.py` covers matching bounded scope, tissue mismatch, missing environmental dimensions, unknown claim scope, global scope, and transparent retention of out-of-scope reasoning paths.

Repository CI remains subject to issue #481. This branch therefore remains stacked/draft until workflow jobs execute real steps.
