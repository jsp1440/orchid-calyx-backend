# KERNEL-007 — Knowledge Object Engine

KERNEL-007 introduces curated knowledge syntheses as first-class Scientific Kernel objects.

## Purpose

A `KnowledgeObject` assembles reviewed assertions, relationships, evidence, and publication records into an immutable, citable scientific synthesis. It provides the durable layer consumed by Calyx, Species Atlas, Culture Sheets, conservation tools, and research workspaces.

## Contract

Every knowledge object includes:

- a permanent `KNOWLEDGE_OBJECT` OCID;
- a canonical knowledge category;
- one or more scientific subjects when applicable;
- typed links to assertions, relationships, evidence, and publications;
- lifecycle status;
- title and optional summary;
- curator and reviewer attribution;
- optional supersession lineage;
- read-only structured attributes.

## Validation invariants

- Titles must not be empty.
- Linked OCIDs must be unique within each support category.
- Assertion, relationship, evidence, and publication references must use their matching OCID kinds.
- Accepted, disputed, rejected, and superseded knowledge objects require supporting scientific objects.
- Accepted knowledge objects require reviewer attribution.
- Supersession references must use a different `KNOWLEDGE_OBJECT` OCID.
- Instances and attributes are immutable after construction.

## Knowledge categories

The initial vocabulary includes taxon, trait, distribution, ecological, culture, conservation, literature-synthesis, concept, and generic knowledge objects.

## Service contract

`KnowledgeObjectService` supports publication, direct retrieval, subject-centric lookup, and lookup by supporting scientific object.

## Validation

```bash
python -m pytest -q \
  tests/kernel/test_foundation.py \
  tests/kernel/test_evidence.py \
  tests/kernel/test_assertions.py \
  tests/kernel/test_relationships.py \
  tests/kernel/test_publications.py \
  tests/kernel/test_queries.py \
  tests/kernel/test_knowledge.py
```

Persistence adapters, synthesis materialization, ontology governance, conflict reconciliation, automatic regeneration, and authorization-aware visibility remain deferred to later Kernel milestones.
