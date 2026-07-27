# KERNEL-003 — Assertion Engine

## Purpose

KERNEL-003 introduces the canonical evidence-backed claim model for the Orchid Continuum Scientific Kernel. Assertions express a subject-predicate-object statement while preserving confidence, evidence references, lifecycle status, temporal validity, and review metadata.

## Public contracts

### `Assertion`

An immutable `ScientificObject` with an `ASSERTION` OCID. Each assertion contains:

- a subject OCID;
- a normalized predicate;
- an `AssertionObject` represented by either another OCID or a literal value;
- zero or more unique Evidence OCIDs;
- a normalized `Confidence` score;
- an `AssertionStatus` lifecycle state;
- optional author, reviewer, temporal validity, and qualifiers.

### `AssertionObject`

The object side of a scientific statement. It must contain exactly one of:

- `ocid`, for a relationship to another durable Continuum object; or
- `value`, for a literal value with optional datatype and unit.

### `Confidence`

A score from `0.0` to `1.0`, accompanied by the method used to derive the score and an optional rationale.

### `AssertionStatus`

Supported lifecycle states:

- `draft`
- `proposed`
- `accepted`
- `disputed`
- `rejected`
- `superseded`

## Enforced invariants

1. Assertions are immutable.
2. Assertion identifiers use the `ASSERTION` OCID kind.
3. Predicates cannot be blank.
4. Evidence references must be unique `EVIDENCE` OCIDs.
5. Accepted, disputed, rejected, and superseded assertions require evidence.
6. Confidence scores remain within `[0.0, 1.0]`.
7. Temporal values must be timezone-aware and are normalized to UTC.
8. `valid_until` must occur after `valid_from`.
9. Qualifiers are exposed as a read-only mapping.

## Validation

```bash
python -m pytest -q \
  tests/kernel/test_foundation.py \
  tests/kernel/test_evidence.py \
  tests/kernel/test_assertions.py
```

## Deferred work

KERNEL-003 defines domain contracts only. Persistence adapters, confidence aggregation policies, reviewer authorization, assertion replacement transactions, and graph publication are deferred to later Kernel milestones.
