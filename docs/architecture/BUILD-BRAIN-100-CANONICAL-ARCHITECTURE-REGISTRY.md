# BUILD-BRAIN-100 — Canonical Architecture Registry

## Status
Implemented as a storage-agnostic candidate slice. Not deployed or merged.

## Purpose
Make Orchid Continuum architecture, decisions, intent, dependencies, validation, and reproducibility searchable, discoverable, and repeatable.

## Contracts
The Brain stores strict versioned objects for architecture, decisions, intent, builds, datasets, APIs, engineers, dependencies, validation, reproducibility, and risks. Records include durable IDs, lifecycle state, aliases, tags, source URI, checksum, creation time, version, and optional supersession.

Relationships connect objects through contains, depends_on, supports, implements, documents, validates, owned_by, supersedes, aligned_to, and related_to predicates.

## Implemented behavior
- idempotent registration;
- conflicting durable identity rejection;
- relationship endpoint validation;
- deterministic keyword, alias, tag, summary, and type search;
- deterministic relationship traversal;
- architecture-to-intent alignment queries;
- deterministic canonical snapshots and checksums;
- explicit lifecycle and supersession validation.

## Initial searchable architecture
The fixture records Brain, Mission Control, Knowledge Explorer, Atlas, Research Station, Conservatory, Matrix Identification, AI.Vision, Scientific Publishing, approved Atlas Earth Systems decision, approved Knowledge Explorer decision, and project intents.

## Repeatability
Identical ordered content produces the same snapshot checksum. Search results are ordered by score, normalized title, and durable ID.

## Boundaries
This slice does not add a production database, vector embedding provider, autonomous publication, deployment, production Knowledge Graph writes, or merge authority.

## Next slice
Add a protected read API, repository-document ingestion adapter, persistent repository contract, architecture gap report, and Mission Control summary payload after focused validation passes.
