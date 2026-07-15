# BUILD-065 — Canonical Taxonomy Operator Guide

Read-only. Controlled population still requires explicit owner approval.

## Build / inspect the canonical registry (safe, no writes)
```python
from runtime.knowledge_graph import (
    build_canonical_registry, select_canonical_release, WorldPlantsRelease)
canonical, releases = select_canonical_release(all_world_plants_releases)
reg = build_canonical_registry(load_rows, synonym_rows, authority_rows,
                               canonical_release=canonical)
print(reg.summary())
reg.resolve("Cattleya gigas")   # -> accepted taxon (follows synonyms)
```

## Rules the operator must uphold
- **One canonical taxonomy.** Only World Plants taxa are canonical. Do not
  reintroduce POWO/GBIF as competing backbones — attach them as mappings.
- **Never delete a superseded/historical release.** Preserve provenance.
- **Never auto-publish a fuzzy mapping.** Only `exact_id`,
  `authority_supported_synonym` and `accepted_name_mapping` are auto-publishable;
  everything else is `manual_review_required`.
- **Activation is gated.** Only `ACTIVATED_DOMAINS` (media, traits, pollinators,
  occurrences) may be populated now; withheld domains stay disabled until their
  blocking issue is resolved.

## Conflicts to review before broader publication
- 376 unresolved synonym chains (synonym → synonym) — resolve to accepted taxa.
- 323 authority disagreements (one taxon, two ids from one authority) — pick the
  current id. See `Taxonomic_Conflict_Report.xlsx`.
