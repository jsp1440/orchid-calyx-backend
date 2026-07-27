# KERNEL-004 — Relationship Engine

KERNEL-004 introduces first-class scientific relationships for the Orchid Continuum Scientific Kernel.

## Purpose

A relationship is not an anonymous graph edge. It is an immutable, globally identified scientific object that can be cited, reviewed, disputed, superseded, and traversed.

## Contract

Every `Relationship` includes:

- a permanent `RELATIONSHIP` OCID;
- source and target OCIDs;
- a canonical relationship type;
- directed or bidirectional traversal semantics;
- zero or more immutable Evidence OCIDs;
- normalized confidence;
- lifecycle status;
- author and reviewer metadata;
- optional temporal validity;
- read-only qualifiers.

## Validation invariants

- Source and target must differ.
- Evidence references must use `EVIDENCE` OCIDs and must be unique.
- Accepted, disputed, rejected, and superseded relationships require evidence.
- Temporal values must be timezone-aware and are normalized to UTC.
- `valid_until` must be later than `valid_from`.
- Instances and qualifiers are immutable after construction.

## Relationship categories

The initial canonical vocabulary includes parentage, pollination, mycorrhizal association, occurrence, traits, evidentiary support, derivation, synonymy, ecological interaction, and a general related-to fallback.

## Traversal

Directed relationships may be traversed from source to target. Bidirectional relationships may be traversed from either endpoint. The `RelationshipService` contract supports retrieval, object-centric listing, and bounded-depth traversal.

## Validation

```bash
python -m pytest -q \
  tests/kernel/test_foundation.py \
  tests/kernel/test_evidence.py \
  tests/kernel/test_assertions.py \
  tests/kernel/test_relationships.py
```

Persistence adapters, graph indexes, cycle policies, ontology-governed predicates, and publication transactions are deferred to later Kernel milestones.
