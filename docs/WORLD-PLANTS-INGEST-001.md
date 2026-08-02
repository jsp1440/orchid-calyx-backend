# WORLD-PLANTS-INGEST-001 — Governed Hassler Taxonomy Release Intake

## Source fixture

- File: `WorldOrchids 26-08 (Aug 2 2026).csv`
- Acquired: 2026-08-02
- Source: World Plants, Dr. Michael Hassler
- Delimiter: pipe (`|`)
- Header width: 13 fields
- Actual data width: 22 fields
- Rows: 34,724
- SHA-256: `e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`

The original file is not committed to Git. Production intake must register the exact
bytes in immutable source storage and record the checksum in
`oc_source.source_snapshots` before parsing.

## What this build provides

- side-effect-free 22-field parser;
- UTF-8 first, lossless Latin-1 fallback;
- HTML entity normalization while preserving source fields;
- rank validation for F, SF, T, ST, G, S, SS, V and FM;
- four photo/author/orientation groups;
- raw synonym preservation;
- deterministic old-versus-new release delta;
- duplicate identity detection;
- non-executing owner-gated promotion plan.

## Identity rule

`Number` is preserved as `world_plants_number`, but it is not assumed to be a
universal stable identifier. The first dry-run comparison key is rank plus exact
source name. A later database-backed crosswalk must prefer stable World Plants
numbers when present and route uncertain mappings to manual review.

## Required production stages

1. Register immutable source snapshot and checksum.
2. Load versioned staging rows with source row numbers and raw payloads.
3. Split photo groups into versioned media-reference staging.
4. Preserve and parse synonym assertions without discarding raw text.
5. Compare against the current canonical World Plants release.
6. Generate an old-to-new taxon crosswalk and conflict report.
7. Require authenticated owner approval.
8. Promote atomically; retain the prior release as historical.
9. Rebuild image, occurrence, literature and knowledge-graph relationships.
10. Run coverage, orphan and rollback verification.

## Safety boundary

This build performs no database writes and cannot promote a release. Fuzzy or
ambiguous mappings are never automatically published. No historical release may
be deleted.
