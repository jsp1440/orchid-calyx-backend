# KERNEL-006 — Scientific Query Engine

KERNEL-006 introduces implementation-neutral query contracts for retrieving Orchid Continuum Scientific Kernel objects.

## Purpose

The Scientific Query Engine provides a stable boundary between Kernel consumers and future persistence implementations. Calyx, Atlas, Oasis, research workspaces, and API adapters can express the same bounded scientific query without depending on a specific database or search engine.

## Query contract

`ScientificQuery` supports:

- one or more scientific object categories;
- direct OCID selection;
- object-centric linked-OCID filtering;
- lifecycle status filtering;
- predicate filtering;
- normalized text search input;
- read-only implementation-specific filters;
- deterministic multi-field sorting;
- bounded limit and non-negative offset pagination;
- optional inclusion of superseded records.

Selectors must be unique. Empty status and predicate values are rejected. Result limits are constrained to 1–1000 records.

## Result pages

`QueryPage` provides an immutable result tuple, total result count, limit, offset, and a `has_more` indicator. Page totals cannot be negative or smaller than the number of returned items.

## Service boundary

`ScientificQueryService` defines:

- `execute(query)` for retrieving a bounded page;
- `count(query)` for obtaining the matching total;
- `get(ocid)` for direct object lookup.

The contract does not prescribe PostgreSQL, graph, full-text, or external search implementation details.

## Validation

```bash
python -m pytest -q \
  tests/kernel/test_foundation.py \
  tests/kernel/test_evidence.py \
  tests/kernel/test_assertions.py \
  tests/kernel/test_relationships.py \
  tests/kernel/test_publications.py \
  tests/kernel/test_queries.py
```

Persistence adapters, query planning, graph expansion, relevance scoring, faceting, cursor pagination, and authorization-aware visibility remain deferred to later milestones.
