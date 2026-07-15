# BUILD-064 Deliverable 9 — Updated Operator Guide

Supersedes the connection notes in the BUILD-062 operator guide. Everything
here is read-only; controlled population still requires explicit authorization.

## What changed since BUILD-062
- The source registry now records **connection quality** per domain: status,
  identifier strategy, join strategy, crosswalk-required, confidence, expected
  vs actual counts, last verification, operator notes
  (`registry_by_domain()[domain].metadata`).
- A reusable **taxonomic crosswalk** was produced:
  `docs/crosswalks/orchid_taxonomy_to_backbone_crosswalk.csv`
  (`orchid_taxonomy.id → taxonomy_species.id`, 10,409 pairs, confidence-scored).
- Climate is now classified **BLOCKED** (proxy, not climate).

## Per-domain population guidance
| Domain | Decision before you populate |
| --- | --- |
| media | Ready — direct id join. Populate freely. |
| pollinators | Ready with review — 4 clean taxa; tiny. Populate, spot-check. |
| occurrences | Review — only 26 curated rows. Do **not** repoint to `orchid_occurrence` (580k) until its taxon linkage is verified; `accepted_taxon_id` resolves only ~504 taxa and `oc_occurrences.species_id` resolves none. |
| traits | Review — resolved-view id join, ~43% coverage; remainder lack consensus rows. |
| mycorrhiza | Partial — 44% orphan names, 32 colliding names inflate 462 rows → 626 edges. Apply the crosswalk or review collisions before populating. |
| literature | Partial — no upstream taxon id (pure name join); 25% orphan. Populate only matched edges knowingly. |
| conservation | Partial — only 2 rows; CITES tables empty. Await data ingestion. |
| climate | **Blocked** — connected source is an occurrence-derived proxy; real climate tables (`species_climate_profile_monthly` etc.) are empty. Do not present as climate. |

## How to inspect (safe any time)
```python
import os
from runtime.knowledge_graph import (
    BuildOrchestrator, ExecutionMode,
    PostgresGraphRepository, PostgresSourceProvider, InMemoryCheckpointStore)
dsn=os.environ["DATABASE_URL"]
repo=PostgresGraphRepository(dsn); src=PostgresSourceProvider.from_registry(dsn)
print(BuildOrchestrator(repo, src).run(ExecutionMode.AUDIT)["preflight"])
dry=BuildOrchestrator(repo, src, checkpoint_store=InMemoryCheckpointStore(),
                      batch_size=500).run(ExecutionMode.DRY_RUN)
print(dry["totals"], dry["build"]["wrote_to_production"])  # -> ..., False
```

## Using the crosswalk to upgrade name-join domains
For pollinators/mycorrhiza, join on `orchid_taxonomy_id` through the crosswalk
CSV (or `oc_taxonomy.taxon_crosswalk`) instead of the domain's free-text name.
The final hop to the backbone remains a canonical-name equality — there is no
pure-id bridge between the orchid-legacy and KG backbones (they link to GBIF and
POWO respectively). Literature cannot be upgraded until its extractor emits an id.

## Authorizing controlled population (unchanged, still not done)
Population requires `authorized_to_publish=True` **and** `ExecutionMode.PUBLISH`.
Prefer one domain at a time; publication is idempotent (canonical-key skip).
