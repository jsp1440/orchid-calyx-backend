# BUILD-062 — Scientific Knowledge Graph: Real Source-Data Connection Report

Branch: `feat/scientific-knowledge-graph-completion` · Mode of execution: **read-only**
(AUDIT + DRY_RUN only). **No production graph was published. PUBLISH/RESUME were
not authorized. No migrations, no production writes.**

## 1. Objective

Connect the eight BUILD-060 scientific domain adapters (occurrences, traits,
pollinators, mycorrhiza, conservation, climate, literature, media) to **real
production source data** in the `orchid-calyx-backend` production database, via a
single **config-driven source-query registry** consumed by
`PostgresSourceProvider` — no scattered SQL. All source queries are SELECT-only
and enforced safe at construction and execution time.

## 2. What was built

| Artifact | Purpose |
| --- | --- |
| `runtime/knowledge_graph/source_registry.py` | Single home for all per-domain read-only projection SQL. `SourceQuery` dataclass, 8 domain configs, `assert_safe_sql`, `enabled_queries()`, `blocked_domains()`, `registry_by_domain()`. |
| `runtime/knowledge_graph/sources.py` | `PostgresSourceProvider.from_registry(dsn)` builds directly from the registry; SQL safety enforced on construction **and** per-fetch (defence in depth). |
| `runtime/knowledge_graph/adapters.py` | Adapter `source_table` + `label_fields`/`payload_fields` aligned to the real production columns/aliases each query emits. |
| `runtime/knowledge_graph/__init__.py` | Registry API exported at package level. |
| `tests/test_source_registry.py` | 37 tests: registry contract, SQL-safety allow/deny, taxon mapping, adapter output shape, zero-write AUDIT/DRY_RUN, publish-authorization-disabled. |

### SQL safety

`assert_safe_sql` strips comments, rejects multi-statement input, requires the
statement to begin with `SELECT`/`WITH`, and rejects any forbidden keyword
(`insert/update/delete/merge/create/alter/drop/truncate/grant/revoke/copy/call/
do/vacuum/comment/reindex/refresh/lock/listen/notify/execute`). Every registered
query is validated; the provider re-validates on construction and again before
each fetch.

## 3. Production schema audit (read-only)

Taxon backbone: **`oc_graph.kg_nodes`** where `node_type='taxon'`, with
`source_pk = public.taxonomy_species.id` (33,786 taxa, ids 1..33786). Every
projection filters to taxa present in this backbone so all projected edges
resolve. Three taxon-mapping strategies are used:

- **direct** — the source carries a backbone-space taxon id.
- **resolved_view** — a curated view already resolved the taxon id.
- **name_join** — source has no backbone taxon id; exact case-insensitive join
  on scientific name to `kg_nodes.display_label` (a natural-key relational join,
  not fuzzy matching). Name collisions can fan one source row to multiple taxa.

## 4. Live DRY_RUN results (real production data, zero writes)

`wrote_to_production: False` for both AUDIT and DRY_RUN. DRY_RUN duration ≈ 109 s.

| Domain | Source table | Mapping | Rows | Nodes | Edges | Invalid | Classification |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| occurrences | `oc_atlas.occurrences` | direct | 26 | 26 | 26 | 0 | **FULLY CONNECTED** (low volume) |
| traits | `oc_views.trait_resolved_v4` | resolved_view | 2807 | 2807 | 2807 | 0 | **FULLY CONNECTED** (~43% taxa coverage) |
| pollinators | `oc_interactions.orchid_interaction_edges` | name_join | 23 | 23 | 23 | 0 | **PARTIALLY CONNECTED** |
| mycorrhiza | `oc_mycorrhiza.orchid_fungal_associations` | name_join | 626 | 291 | 626 | 0 | **PARTIALLY CONNECTED** |
| conservation | `oc_conservation.conservation_records` | direct | 2 | 2 | 2 | 0 | **FULLY CONNECTED** (very low volume) |
| climate | `oc_env_intel.species_environment_profile` | direct | 19263 | 19263 | 19263 | 0 | **PARTIALLY CONNECTED** (proxy) |
| literature | `oc_graph.taxon_literature_edges` | name_join | 29 | 29 | 29 | 0 | **PARTIALLY CONNECTED** |
| media | `oc_api.species_media_gallery_v1` | direct | 51 | 51 | 51 | 0 | **FULLY CONNECTED** |

**Totals:** 22,492 projected nodes · 22,827 projected edges · **0 invalid rows.**

Data-quality validation on the projected content is **clean**: 0 invalid
canonical keys, 0 duplicate edges, 0 dangling/orphan edges, 0 endpoint
mismatches, vocabulary fully compliant, 0 missing provenance.

### On the 14,481 "orphan nodes"

Cross-domain validation reports `total_problems: 14481`, **all** of which are
`orphan_nodes` — backbone **taxon** nodes in the seeded staging graph that have
no domain edge yet. This is **coverage sparsity, not a data defect**: most of the
33,786 taxa simply have no occurrence/trait/etc. record in production yet. It is
an artifact of validating a taxonomy-seeded staging graph and does not indicate
any problem with the projected domain data.

## 5. Per-domain findings & caveats

- **media** — `oc_core.media_assets.taxon_id` is entirely NULL; the curated
  `oc_api.species_media_gallery_v1` view carries the resolved taxonomy id and is
  used instead. `source_pk` is a deterministic hash of `(taxonomy_id, media_url)`.
- **traits** — `oc_traits.traits` has no taxon column; consensus view
  `trait_resolved_v4` resolves it. Coverage ≈ 2,807 / 6,644 trait taxa in the
  backbone (~43%). `source_pk` is a hash of `(taxonomy_id, trait_name, value)`.
- **climate** — **No true bioclim table exists.** `species_environment_profile`
  is an **occurrence-derived environmental proxy** (elevation stats + qualitative
  `climate_proxy_zones`), not modelled WorldClim/bioclim variables. Real bioclim
  requires a future derivation pipeline from occurrence coordinates.
- **pollinators / mycorrhiza** — the interaction/association tables key orchids
  by an `orchid_taxonomy_id` in the **oc_taxonomy id space** (values above the
  backbone max) with **no verified crosswalk** to the graph backbone. An exact
  scientific-name join is used. Mycorrhiza name collisions expand 291 distinct
  taxa/462 base associations to 626 edges.
- **literature** — `taxon_literature_edges` keys taxa by scientific_name only;
  exact name join used.
- **occurrences / conservation** — direct taxon-id joins, fully clean, but very
  low production volume (26 and 2 rows respectively).

## 6. Constraints honored

- Source access **read-only**; both runs report `wrote_to_production: False`.
- **No production graph publish.** PUBLISH/RESUME **not** authorized
  (`publish_authorized: False`).
- No migrations, no production writes, no schema changes.
- PR #56 **not merged.** Work committed to `feat/scientific-knowledge-graph-completion`.

## 7. Readiness assessment

Every domain now reads real production data through a single safe, config-driven
registry, and projected data validates cleanly. However, no domain is
unambiguously production-clean for an unattended publish: climate is a derived
proxy (not bioclim); pollinators, mycorrhiza, and literature rely on
scientific-name joins with known collision fan-out and no verified id crosswalk;
occurrences and conservation carry very low volume. These require operator
review and per-domain go/no-go decisions before any controlled population.

## NOT READY FOR CONTROLLED PRODUCTION POPULATION
