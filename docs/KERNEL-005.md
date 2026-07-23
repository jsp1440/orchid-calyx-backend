# KERNEL-005 — Publication and Transaction Engine

KERNEL-005 introduces immutable publication transactions for atomically releasing scientific objects into the Orchid Continuum.

## Purpose

A publication is a durable scientific object that groups assertions, relationships, evidence, and other kernel objects into one reviewable and citable release boundary.

## Contract

Every `Publication` includes:

- a permanent `PUBLICATION` OCID;
- an immutable manifest of included object OCIDs;
- optional root objects that identify the publication's principal entries;
- lifecycle status;
- preparation and commit actors;
- an optional UTC commit timestamp;
- optional supersession linkage;
- optional rejection rationale;
- read-only annotations.

## Lifecycle

The initial lifecycle is:

- `draft`
- `prepared`
- `committed`
- `rejected`
- `superseded`

Committed publications require `prepared_by`, `committed_by`, and `committed_at`. Rejected publications require a reason. Superseded publications require a publication OCID identifying the preceding release.

## Atomicity boundary

The publication manifest defines the complete set of scientific objects intended to commit together. Persistence implementations must either make the complete manifest visible or make none of it visible.

## Validation invariants

- A manifest contains at least one object.
- Manifest object and root OCIDs are unique.
- Every root must appear in the object manifest.
- Publication identity uses a `PUBLICATION` OCID.
- Commit timestamps are timezone-aware and normalized to UTC.
- Commit timestamps cannot precede creation.
- Publication instances, manifests, metadata, and annotations are immutable.

## Service contract

`PublicationService` defines preparation, atomic commit, rejection, retrieval, and object-centric publication lookup. Persistence adapters, database transactions, locking, idempotency keys, and event dispatch remain implementation concerns for subsequent milestones.

## Validation

```bash
python -m pytest -q \
  tests/kernel/test_foundation.py \
  tests/kernel/test_evidence.py \
  tests/kernel/test_assertions.py \
  tests/kernel/test_relationships.py \
  tests/kernel/test_publications.py
```
