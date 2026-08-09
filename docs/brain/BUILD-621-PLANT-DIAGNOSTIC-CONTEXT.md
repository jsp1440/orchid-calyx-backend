# BUILD-621 — Plant Diagnostic Context Composer

## Status

Implemented on `feature/build-621-plant-diagnostic-context`, stacked on BUILD-620. This build must not merge before the BUILD-615→620 prerequisite stack is validation-cleared and GitHub hosted-runner issue #481 is resolved.

## Purpose

BUILD-621 composes two evidence channels needed for real Orchid Continuum plant diagnosis:

1. canonical, scope-aware mechanistic pathways from BUILD-619; and
2. bounded local plant observations from BUILD-620.

The composer presents them together without collapsing them into one scientific claim.

## API

Protected Brain endpoint:

`POST /brain/diagnostic-context`

Input contains:

- `plant_record_key`;
- a complete BUILD-619 `ScopedReasoningMapRequest`, including subject node and explicit applicability scope.

## Output channels

### Canonical reasoning

`canonical_reasoning` is the BUILD-619 scoped reasoning map. Paths remain classified as:

- applicable;
- out of scope;
- indeterminate.

### Local observation context

`local_observation_context` is the BUILD-620 plant history. These records remain:

- `CULTIVATION_OBSERVATION` evidence;
- plant-local;
- bounded to time/location/context;
- `n=1` where created as a single-plant event;
- non-causal;
- non-generalizable;
- outside canonical publication authority.

## Interpretation policy

The response explicitly declares:

- canonical mechanisms and local observations are separate evidence channels;
- a local observation does not imply a canonical mechanism;
- similarity is not causality;
- unknown scope is not assumed applicable;
- diagnostic hypothesis generation is permitted;
- automatic scientific claim generation is prohibited;
- automatic publication is prohibited.

This is the central safety rule for using Conservatory/Matrix data with the scientific Reasoning Map.

For example, if a plant develops roots after a temperature change and a published pathway describes temperature-sensitive root physiology, BUILD-621 may present both facts in one diagnostic context. It does **not** assert that the temperature change caused that individual plant's root growth.

## Summary fields

The composer reports:

- applicable canonical path count;
- out-of-scope canonical path count;
- indeterminate canonical path count;
- local observation count;
- whether any applicable canonical context exists;
- whether any local observation context exists.

These counts support UI and later Calyx answer composition without introducing hidden inference.

## Governance

BUILD-621 is read-only.

It cannot:

- mutate the canonical graph;
- mutate Candidate Knowledge;
- approve local observations;
- resolve contradictions;
- promote an observation into a mechanistic candidate;
- publish a scientific claim;
- infer that co-occurrence establishes causality.

Any new mechanistic hypothesis derived from comparison of canonical pathways and local plant history must enter a separate governed hypothesis/review workflow.

## Validation

`tests/test_build_621_plant_diagnostic_context.py` verifies:

- canonical and local evidence remain separate channels;
- applicable canonical paths and local observations can coexist without causal promotion;
- an empty local history is represented honestly rather than invented;
- out-of-scope canonical pathways remain visible and non-applicable;
- the composer is read-only and has no publication authority.

The dedicated BUILD-621 workflow also reruns BUILD-620 local-observation tests, BUILD-619 scoped reasoning tests, route verification, Ruff, formatting, compile, and hygiene.

## Next dependency

After executable CI returns, the next high-value layer is a governed **diagnostic hypothesis builder** that may propose ranked explanations from this context but must:

- label each explanation as a hypothesis;
- cite canonical pathway evidence separately from local observations;
- expose contradictory/out-of-scope evidence;
- never publish automatically;
- preserve a review/audit trail.
