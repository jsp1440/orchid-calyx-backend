# CALYX-BRAIN-001A — Literature-to-Candidate Knowledge Handoff

## Architecture impact statement

This is the smallest operational bridge identified by the Calyx Brain program audit. It extends PR #145 / Issue #141 and reuses BUILD-086A candidate knowledge. It does not implement the Reasoning Ledger in Issue #142 or Data Intelligence in Issue #143.

The change is additive: no migration, schema replacement, extractor reorder, existing API change, or automatic publication is introduced.

## Contract

`POST /api/literature-extraction/papers/{paper_id}/candidate-handoff` is authenticated and accepts identities already assigned by intake/document intelligence:

- canonical source object and revision IDs;
- canonical extraction run ID;
- a mapping from each literature evidence ID to its canonical source-anchor ID;
- source display and internal-use policy.

The adapter supports only normalized domains that have an existing `CandidateKind`. Each eligible record must have exactly one subject across canonical and unresolved entities. Unsupported domains, missing evidence bindings, and ambiguous or missing subjects are returned as explicit blocked records. If no record is eligible, the request fails with `NO_ELIGIBLE_CANDIDATES` and writes no candidate run.

The adapter copies original character offsets, section, claim ID, paper/analysis IDs, evidence ID, and source hash into the existing candidate evidence link. It does not alter source text or resolve unresolved names. Repeat requests reuse the existing deterministic candidate fingerprint.

All resulting candidates remain `review_state=REQUIRED` and `published=false`. Existing candidate review and publication gates remain authoritative.

## Known limitations

- Canonical source bindings are caller-supplied and validated only for shape/positive identity; a later build must resolve and transactionally verify them against document-intelligence persistence.
- Records with multiple possible subjects are blocked rather than split or guessed.
- The adapter does not add labels, synonyms, concept resolution, relationships, memory, reasoning, search, or dataset processing.
- Candidate repositories retain their existing deployment characteristics; this slice does not replace snapshot persistence with a new database design.

## Validation

The focused suite verifies end-to-end extraction and handoff, provenance/offset preservation, review-only state, no publication, deterministic reuse, explicit ambiguity blocking, API authentication, and metadata-only quote policy. Existing literature and BUILD-086A regression suites remain required.
