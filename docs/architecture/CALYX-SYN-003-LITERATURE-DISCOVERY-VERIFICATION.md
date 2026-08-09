# CALYX-SYN-003 — Literature Discovery and Bibliographic Verification

## Mission

Give Calyx a real external literature-discovery path without allowing search results, model memory, or approximate metadata to masquerade as verified scientific sources.

## Provider boundary

The first operational provider is Crossref. Calyx uses the Crossref `/works` search path for discovery candidates and the DOI-specific `/works/{doi}` lookup for authoritative bibliographic verification.

Discovery and verification are intentionally separate operations:

`research question -> discovery candidates -> DOI resolution -> authoritative lookup -> verified bibliography record`

A search result is never marked verified merely because it contains a DOI.

## Runtime API

Authenticated beneath Scientific Synthesis:

- `POST /api/scientific-interpretation/synthesis/discovery/search`
- `POST /api/scientific-interpretation/synthesis/discovery/verify-doi`

Search output explicitly declares:

- `search_results_are_evidence: false`
- `search_results_are_verified: false`

Successful DOI verification produces a `BibliographicRecord` compatible with CALYX-SYN-001 and includes:

- normalized DOI source identity
- title
- authors
- publication year when available
- journal/container title when available
- `VERIFIED_AUTHORITY`
- `verification_provider: crossref`
- exact verification identifier
- `AUTHORITATIVE_DOI_LOOKUP` method

## Verification blockers

A DOI remains unresolved when:

- DOI input is missing or invalid
- authoritative DOI lookup returns no record
- returned DOI does not exactly match the requested normalized DOI
- authoritative metadata lacks a title or authors
- provider access fails

Provider access failures surface as `LITERATURE_PROVIDER_UNAVAILABLE`; they never degrade into fabricated metadata.

## Deduplication

Discovery candidates are deterministically deduplicated by normalized DOI when present. Records without a DOI use a deterministic title/year/authors signature. Candidate IDs and the discovery-manifest fingerprint are deterministic for identical provider results.

## Governance invariants

- Search candidates are not evidence.
- Search candidates are not verified bibliography.
- Model memory is not a verification provider.
- Verification provenance is provider-attributed.
- No paper is acquired, extracted, interpreted, or published by this slice.
- No Knowledge Graph mutation occurs.
- CALYX-SYN-001 remains the article publication-readiness gate.

## Next dependency

CALYX-SYN-004 maps verified/acquired literature and exact evidence anchors into study-level evidence-matrix rows. It may use discovery metadata for navigation but scientific result fields must come only from source-bound extracted evidence.
