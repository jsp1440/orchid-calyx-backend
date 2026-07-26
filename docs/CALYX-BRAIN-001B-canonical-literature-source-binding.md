# CALYX-BRAIN-001B — Canonical Literature Source Binding

## Purpose

This build removes the remaining manual provenance precondition between verified literature extraction and governed candidate knowledge. It persistently binds a literature paper and its evidence records to canonical source identities owned by intake/document intelligence.

## Runtime contract

Authenticated endpoints:

- `PUT /api/literature-extraction/papers/{paper_id}/source-binding`
- `GET /api/literature-extraction/papers/{paper_id}/source-binding`
- `POST /api/literature-extraction/papers/{paper_id}/candidate-handoff`

The binding records canonical source object, document revision, extraction run, evidence-to-anchor mappings, display policy, internal-use permission, and language. Identical replay is idempotent. A conflicting rebind fails without changing the existing binding.

Candidate handoff resolves the persisted binding by default. Persisted state is authoritative and cannot be silently overridden by an incompatible caller-supplied binding.

## Persistence and rollback

The implementation is additive and uses an atomic file replacement within the established literature output-bundle directory:

`runtime/literature_extraction/{paper_id}/source-binding.json`

No existing literature bundle or candidate-knowledge schema is replaced. Rollback consists of removing this additive binding file and reverting the route wiring; existing paper output bundles and candidates remain unchanged.

## Scientific and governance invariants

- Canonical identifiers are supplied by intake/document intelligence and are never synthesized by literature extraction.
- Foreign evidence IDs and incomplete mappings are rejected before persistence or handoff.
- Source offsets, evidence IDs, source hashes, confidence, display policy, and provenance continue through the existing candidate adapter.
- Candidates remain review-required and unpublished.
- No concept resolution or scientific publication occurs automatically.

## Structured failures

- `CANONICAL_SOURCE_BINDING_NOT_FOUND`
- `CANONICAL_SOURCE_BINDING_REQUIRED`
- `CANONICAL_EVIDENCE_BINDING_MISSING`
- `ANCHOR_EVIDENCE_IDS_NOT_IN_PAPER`
- `CROSS_PAPER_BINDING`
- `CONFLICTING_SOURCE_REBIND`
- `PERSISTED_BINDING_IS_AUTHORITATIVE`

## Known limitation

The repository does not yet expose a unified transaction spanning document-intelligence storage, literature binding persistence, and candidate persistence. This build makes the literature-side binding durable, atomic, validated, and authoritative without inventing a new document-intelligence schema. A future database convergence build may move the same contract into PostgreSQL while retaining these identities and failure semantics.
