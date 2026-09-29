# Orchid Continuum Software Factory v1

Status: implementation contract for `oc-autonomous-integration`.

## Purpose

Convert the Orchid Continuum completion system from prompt-driven coding sessions into a durable, repository-native software factory. GitHub issues, pull requests, checks, and machine-readable mission state are the control plane. Model sessions are replaceable workers.

## Core loop

`queued -> running -> validating -> done`

A failure during maker work or checker validation becomes a bounded repair lineage. A genuine unavailable dependency becomes `blocked`. An unchanged material fingerprint is a no-op rather than a new run.

## Roles

### Orchestrator

The orchestrator selects the highest-priority unblocked mission, maintains mission state, routes work, recovers failed sessions, and advances to the next executable mission. It does not serve as scientific authority and does not bypass protected boundaries.

### Maker

The maker implements one bounded acceptance criterion. The maker may run its own local tests but cannot be the independent acceptance checker for automatic integration.

### Checker

The checker evaluates the exact maker head SHA against the acceptance criterion and required checks. The checker must be logically independent from the maker identity. A failing checker routes the mission to repair; an inconclusive checker keeps the mission in validation.

## Risk-based integration

Automatic integration is allowed only when all of the following are true:

- target is a non-`main` integration branch;
- the work is reversible;
- no production mutation or deployment is involved;
- no credential/security authority changes are involved;
- no scientific-authority/taxonomy activation/publication change is involved;
- no sensitive locality is exposed;
- no spending is authorized;
- no destructive operation is involved;
- the exact head SHA has independent checker PASS evidence;
- required checks are proven passing;
- risk tier is low or moderate.

Anything outside that envelope fails closed to an owner gate.

## NO-API mode

When NO-API mode is active, a mission that requires a separately billed model/provider call is parked rather than dispatched. Deterministic repository-native work, tests, reconciliation, queue maintenance, and subscription-native execution adapters may continue only where separately authorized and technically supported.

## Durable state

`MissionState` records:

- mission id;
- linked issue number;
- queue lifecycle status;
- material fingerprint;
- attempt count;
- maker identity;
- checker identity;
- last transition reason.

The state belongs in durable repository/GitHub surfaces, not in chat memory. A scheduler must be able to reconstruct the next action after a model session disappears.

## Integration boundary

`FactoryDecision.integration_authorized` means only that the factory policy admits a safe integration-branch action. It is not authority to merge to `main`, deploy production, mutate the production Knowledge Graph/database, activate taxonomy, publish governed scientific knowledge, expose privileged credentials, spend money, or perform destructive actions.

## Next wiring slices

1. Feed Queue Bridge completion events into the factory policy after exact-head reconciliation.
2. Persist mission-state transitions as deterministic GitHub issue/PR metadata.
3. Add a checker dispatch lane separate from the maker lane.
4. Teach the scheduler to auto-integrate only when the factory decision is `AUTO_INTEGRATE`.
5. Record repair lineage and enforce the existing bounded retry ceiling.
6. Mirror the same factory contract into the frontend scheduler and Brain architecture records.
