# CALYX-SYN-002 — Exact Source Anchor Integrity

## Mission

Guarantee that every literature evidence record used downstream by Candidate Knowledge, Evidence Aggregation, Scientific Interpretation, or Scientific Synthesis remains provably bound to the exact immutable source bytes and exact original excerpt from which it was extracted.

Normalized text is a derived representation. It must never become the authority for source locators, source hashes, or excerpt hashes.

## Implemented contract

Canonical literature source bindings now retain an `evidence_integrity` proof for every evidence ID. Each proof contains:

- canonical anchor ID
- SHA-256 of the immutable raw source bytes
- SHA-256 of the exact evidence excerpt
- exact character start/end offsets
- source section identity
- evidence type

The proof is deterministically regenerated from `raw.txt` and the original `PaperKnowledge.evidence` records. A mismatch blocks binding or downstream handoff.

## Hard failures

- `RAW_SOURCE_NOT_FOUND`
- `RAW_SOURCE_HASH_MISMATCH`
- `RAW_SOURCE_NOT_UTF8`
- `EVIDENCE_SOURCE_SPAN_INVALID`
- `SOURCE_INTEGRITY_PROOF_REQUIRED`
- `SOURCE_INTEGRITY_PROOF_INCOMPLETE`
- `SOURCE_INTEGRITY_PROOF_MISMATCH`
- `CANONICAL_EVIDENCE_INTEGRITY_MISMATCH`

Existing source-identity failures remain authoritative, including cross-paper, incomplete evidence mapping, foreign evidence IDs, and conflicting rebinds.

## Runtime boundaries

`PUT /api/literature-extraction/papers/{paper_id}/source-binding`

The route now loads the immutable persisted raw bytes, verifies the paper-level content hash, verifies every evidence span/excerpt, derives exact integrity proofs, and only then persists the canonical binding.

`POST /api/literature-extraction/papers/{paper_id}/candidate-handoff`

The route revalidates the persisted integrity proof against the current immutable raw bytes before Candidate Knowledge receives any evidence. Candidate source-anchor locators carry both `source_hash` and `excerpt_hash` together with exact character offsets.

## Governance invariants

- No new source registry is introduced.
- Canonical source object, revision, extraction-run, and anchor identities remain supplied by the existing intake/document-intelligence boundary.
- Literature normalization cannot replace original evidence text or locators.
- Candidate Knowledge remains review-required and unpublished.
- No Knowledge Graph publication occurs.
- Identical canonical bindings remain idempotent; conflicting rebinds remain blocked.

## Acceptance benchmark

A persisted binding must fail if the raw source bytes are altered, if an excerpt proof is altered, if the source hash becomes stale, if an evidence span no longer reconstructs the original excerpt, or if an evidence/anchor mapping crosses the paper boundary. Successful handoff carries the exact source and excerpt hashes into downstream provenance.
