# BUILD-BRAIN-111 — Immutable Evidence and Artifact Registry

## Status
Implemented on current main as a bounded registry contract. Not deployed and not a publication authority.

## Delivered
- immutable artifact identities and SHA-256 checksums;
- media type, source URI, license, producer assignment, evidence URI, and metadata provenance;
- exact replay idempotency and immutable conflict rejection;
- duplicate-content detection without identity collapse;
- typed lineage and receipt relationships;
- missing-evidence rejection;
- deterministic read-only discovery and snapshots.

## Governance boundary
Registration preserves evidence and lineage only. It does not approve claims, publish science, activate taxonomy, mutate the production Knowledge Graph, merge code, or deploy services.
