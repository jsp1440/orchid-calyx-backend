# BUILD-621-R2 — Plant Diagnostic Context Composer

## Status

Reconstructed on `feature/build-621-plant-diagnostic-context-r2` directly from executable-green BUILD-620-R2 / PR #789. The stale original BUILD-621 stack is not an integration path.

## Purpose

BUILD-621 composes the two evidence channels needed for Orchid Continuum plant diagnosis:

1. canonical, scope-aware mechanistic pathways from BUILD-619; and
2. bounded local plant observations from BUILD-620.

The composer presents them together without collapsing them into one scientific claim.

## API

Protected Brain endpoint:

`POST /brain/diagnostic-context`

Input contains a stable `plant_record_key` and a complete BUILD-619 `ScopedReasoningMapRequest`, including subject node and explicit applicability scope.

## Output channels

`canonical_reasoning` remains the BUILD-619 scoped reasoning map with applicable, out-of-scope, and indeterminate path classifications.

`local_observation_context` remains BUILD-620 plant-local `CULTIVATION_OBSERVATION` evidence, bounded to time/location/context, `n=1` where applicable, non-causal, non-generalizable, and outside canonical publication authority.

## Interpretation policy

The response explicitly declares that canonical mechanisms and local observations are separate evidence channels; a local observation does not imply a canonical mechanism; similarity is not causality; unknown scope is not assumed applicable; diagnostic hypothesis generation may be downstream; automatic scientific claim generation and publication are prohibited.

## Governance

BUILD-621 is read-only. It cannot mutate the canonical Knowledge Graph or Candidate Knowledge, approve observations, resolve contradictions, promote observations into mechanisms, publish scientific claims, activate taxonomy, deploy, or write production data.

Any mechanistic hypothesis derived from the combined context must enter a separate governed hypothesis/review workflow.

## Validation

Focused regressions verify channel separation, coexistence of applicable canonical paths and local observations without causal promotion, honest empty local history, transparent retention of out-of-scope canonical pathways, and read-only/no-publication authority.

The dedicated workflow reruns BUILD-620 and BUILD-619 regressions, verifies the protected diagnostic route, and performs compile, Ruff lint/format, and repository hygiene checks.
