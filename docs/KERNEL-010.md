# KERNEL-010 — Policy and Governance Engine

KERNEL-010 introduces immutable governance policies and implementation-neutral policy evaluation contracts for the Orchid Continuum Scientific Kernel.

## Purpose

The Kernel now has a first-class way to describe which scientific operations are allowed, denied, or require review. Policies are durable scientific objects rather than hard-coded conditionals hidden inside adapters.

## Models

### `GovernancePolicy`

Each policy includes:

- a stable `KNOWLEDGE_OBJECT` OCID;
- a name and optional description;
- one or more canonical governed actions;
- an allow, deny, or require-review effect;
- draft, active, retired, or superseded lifecycle state;
- deterministic priority;
- immutable structured conditions;
- author and reviewer attribution;
- optional UTC validity window;
- optional supersession lineage.

### `GovernanceRequest`

A request describes the action being evaluated, the actor, optional subject and publication scope, and immutable contextual attributes.

### `GovernanceDecision`

A decision records the resulting effect, the policies used, reasons, and UTC evaluation timestamp.

## Validation invariants

- Policy names must not be empty.
- Every policy must govern at least one unique action.
- Priority must be non-negative.
- Active policies require both an author and reviewer.
- Retired and superseded policies require reviewer attribution.
- Superseded policies require a valid predecessor policy OCID.
- Effective timestamps must be timezone-aware and ordered.
- Publication-scoped requests require `PUBLICATION` OCIDs.
- Decision policy references must be unique `KNOWLEDGE_OBJECT` OCIDs.
- Policy conditions, request context, and decision state are immutable.

## Service contract

`GovernanceService` supports:

- registering policies;
- evaluating governance requests;
- retrieving policies by OCID;
- listing active policies.

Concrete persistence, conflict-resolution algorithms, role directories, signatures, authorization adapters, policy languages, and distributed enforcement remain deferred to later milestones.

## Validation

```bash
python -m pytest -q \
  tests/kernel/test_foundation.py \
  tests/kernel/test_evidence.py \
  tests/kernel/test_assertions.py \
  tests/kernel/test_relationships.py \
  tests/kernel/test_publications.py \
  tests/kernel/test_queries.py \
  tests/kernel/test_knowledge.py \
  tests/kernel/test_events.py \
  tests/kernel/test_runtime.py \
  tests/kernel/test_governance.py
```
