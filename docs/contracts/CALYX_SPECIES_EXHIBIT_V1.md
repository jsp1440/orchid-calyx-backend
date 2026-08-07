# Calyx Species Exhibit Contract v1

Public target: `GET /api/platform/homepage/genus/{genus}/species-exhibit?limit=9`

The backend returns distinct canonical species cards, not merely distinct media rows. Scientific prose is server-owned and evidence-bound; the browser must not invent captions, facts, confidence scores, or fall back to genus-level narrative.

Each card contains:
- `taxon_id`
- `display_name` — normalized binomial for presentation
- `full_scientific_name` — source scientific-name string retained intact
- `authorship` — authorship text separated from the binomial when present
- `accepted_name_status`
- `representative_media` with attribution, license, provenance and explicit identification state
- `caption` — a deterministic species-specific rendering of persisted graph evidence, or `null`
- `distinguishing_fact` — the persisted graph relation rendered for that species, or `null`
- `distinguishing_fact_provenance`
- `evidence_state` (`available` or `provisional` in the current adapter set)
- `confidence` derived only from explicit persisted graph confidence values
- `provenance` anchors
- `unavailable_domains`
- `contradictions`
- `caveats`
- species, graph and evidence `links`
- `evidence_receipt` — deterministic SHA-256 receipt over evidence identifiers, not evidence contents
- compatibility fields `media`, `graph_paths`, `evidence_states`, and `calyx_handoff`

Batch-level fields include `count`, `requested_limit`, `distinct_taxa`, `publication_authority: false`, and `graph_mutation: false`.

Pipeline:

`canonical taxonomy -> deterministic species deduplication -> representative-media selection -> Knowledge Graph paths -> contradiction/availability normalization -> evidence-backed caption/fact projection -> governed public response`

Rules:
- deduplicate by canonical `taxon_id` and normalized binomial;
- never reuse a representative media URL across cards when an unused candidate is available;
- at most one representative card per species;
- missing domains remain explicitly unavailable;
- no genus-level text may be substituted as a species caption;
- if no persisted species relation supports a caption, `caption` and `distinguishing_fact` remain `null` and a caveat explains why;
- confidence is unavailable unless a persisted graph edge supplies an explicit score;
- representative media is source-record evidence and is not independently verified by this contract;
- contradiction markers are surfaced, never silently resolved;
- no browser scientific scoring;
- no automatic identity verification, graph mutation, taxonomy activation, scientific publication, or credential disclosure.

The contract is intentionally additive relative to the earlier packet shape so existing consumers of `media`, `graph_paths`, `evidence_states`, and `calyx_handoff` can continue operating while the richer frontend adopts the governed fields.