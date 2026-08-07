# BUILD-BRAIN-111 — Evidence and Artifact Registry

## Status

Implemented as a bounded, immutable reference registry. Not merged, deployed, published, or connected to production storage.

## Delivered

- artifact registration contracts with SHA-256 checksums, media types, source URIs, licenses, assignment provenance, evidence URIs, and metadata;
- immutable identity with idempotent exact replay and conflict rejection;
- duplicate-content detection without collapsing distinct artifact identities;
- typed lineage relationships for derivation, evidence, receipts, and supersession;
- missing-evidence rejection;
- deterministic read-only discovery, lineage, and snapshot projections;
- focused fail-closed tests.

## Governance

Registration is not scientific approval or publication. The registry stores evidence metadata and relationships only. It does not endorse conclusions, activate taxonomy, mutate the Knowledge Graph, or expose credentials.

## Integration

Executor receipts, lease completion evidence, scheduler snapshots, literature extraction products, Matrix releases, image-analysis observations, and Brain capture candidates can use the same immutable envelope. Durable persistence and protected HTTP discovery can be added after the contract is validated.
