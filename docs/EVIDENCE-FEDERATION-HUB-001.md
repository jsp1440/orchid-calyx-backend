# OC Evidence Federation Hub — source-preserving intake

## Purpose

The Evidence Federation Hub links independent orchid evidence sources to the
existing World Plants/Hassler canonical taxon registry without flattening those
sources into one master spreadsheet.

## Storage roles

- Google Drive is the source vault for original partner files and canonical release files.
- GitHub stores adapters, contracts, tests, and architecture — not private or rights-sensitive source datasets.
- Neon/Postgres is the intended working evidence store after dry-run validation.
- World Plants/Hassler remains the sole canonical taxonomy.
- POWO, WFO, IPNI, GBIF, and other authorities attach as mappings/evidence.

## Initial source adapters

- `iospe_pfahl`: source-reported season, temperature, light, fragrance,
  common name, flower size, narrative description, synonyms, and references.
  IOSPE editorial `!`/`~` markers are preserved but not interpreted.
- `yong_gee`: source-reported publication, etymology, synonyms, distribution,
  habitat, season, scent, morphology, capsule, similar species, notes, and
  references. The current Roger Sawkins file is a representative extract, not
  a complete database export.

## Scientific controls

1. Original row values are preserved and hashed.
2. Assertions remain `review_required`.
3. Exact and Hassler-synonym resolution may link a source row to a canonical
   taxon, but source claims do not become canonical facts.
4. Independent claims are compared field-by-field. Different values remain
   separate claims and are flagged for review; they are not averaged.
5. Raw partner files are not committed to the public repository.
6. Rights/display scope is a gate before public redistribution of bulk text or images.

## External federation

Firecrawl is reconnaissance only. It maps public source structure and discovers
stable identifiers, API/download/DwC-A surfaces, citation and licence pages.
Once a sanctioned machine-readable route is known, a dedicated connector should
be preferred over page scraping.

The first live pilots (POWO and WFO, 2026-09-29) successfully established the
federation path and exposed identifiers. Additional external sources are
registered separately with discovery/connector status so planned sources are
not misrepresented as already ingested.
