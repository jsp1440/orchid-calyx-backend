# Verified World Plants → Knowledge Graph Taxon Mapping

**Module:** `runtime/knowledge_graph/canonical_graph_mapping.py` (`oc-taxon-graph-mapping-v1`)
**Offline runner:** `scripts/build_taxon_graph_mapping.py`
**Consumer:** the graph-grounded reasoning pilot, through `GraphGroundedReasoner(taxon_node_key=mapping.taxon_node_key(registry))`
**Stacked on:** #1819

## Problem

The two sides share no identifier, so every join between them is by name.
- `CanonicalRegistry` (BUILD-065, World Plants authority) identifies taxa by an ordinal `canonical_id` assigned in row order.
- `oc_graph.kg_nodes` identifies species as `taxon:<public.taxonomy_species.id>`.
- The graph's source table carries no World Plants identifier (`docs/BUILD-064-01-identifier-crosswalk-report.md`).

The only existing production name join is `app.species_exhibit.service.graph_taxon_keys`, which fails closed when more than one node matches. Everywhere else, a name join is where one species can be silently substituted for another.

## Rule

A World Plants name links to **at most one** active graph `taxon` node. It links **only** when that link is provably unique on both sides. Every other case yields no node key, plus a machine-readable reason:

| Reason | Case |
|---|---|
| `REGISTRY_HOMONYM` | One canonical name, several World Plants rows (different authorship or rank). `build_canonical_registry` keeps the first silently. |
| `PRO_PARTE_SYNONYM` | One synonym name with several accepted targets. The registry keeps the first silently. |
| `SYNONYM_IS_ACCEPTED_NAME` | A name that is both accepted and a synonym. |
| `NAME_NORMALIZATION_UNSAFE` | `canonical_name_of` would collapse the name: `var.`/`subsp.`/`f.`, hybrid markers, or lowercase author particles such as `de Vogel`. |
| `GRAPH_DUPLICATE_LABEL` | Several active graph taxon nodes carry the same canonical label. |
| `GRAPH_HAS_SEPARATE_NODE_FOR_SYNONYM` | The graph has its own node for a synonym. Mapping it to either node would substitute one taxon for the other. |
| `AUTHORITY_ID_CONFLICT` | An external ID (e.g. POWO) differs between registry and node. When IDs agree, the link is classed `MAP_EXACT_ID`; otherwise `MAP_ACCEPTED_NAME`. |
| `GRAPH_NODE_NOT_FOUND` / `SYNONYM_TARGET_NOT_LINKED` | Nothing to link to. Status `unresolved`. |

**Status vocabulary.** `status` uses the Functional Interaction Layer taxon-link values from #1810: `accepted`, `synonym`, `ambiguous`, `unresolved`. Each link also carries `authority: world_plants`, `method: exact_canonical_name` and `automatic_fuzzy_matching: false`. #1810's `TaxonResolutionPolicy(role="provides")` can therefore declare this mapping without a new vocabulary.

**How synonyms link.** A synonym links to its accepted taxon's node, and the link records the accepted name. A synonym never gets its own node.

**What the pilot does with an unverified link.** It reports `TAXON_GRAPH_LINK_UNVERIFIED` and reads no graph data. Its existing focal-node identity check stays as a second guard.

## What it is not

- It is not a second taxonomy. World Plants remains the only authority (`canonical_taxonomy.CANONICAL_AUTHORITY`).
- `strict_name_key` is used only to *detect* collapse; it is not an identity scheme.
- It does not change `canonical_name_of` or the registry. Changing the shared normaliser would re-key existing identities, so that is a separate, owner-reviewed decision.
- It does not read or write a database, and does not activate taxonomy or publish anything.
- Name agreement is not proof of identity. Even an `accepted` link is a unique exact-name agreement, so the mapping class stays `MAP_ACCEPTED_NAME` unless an external ID corroborates it.

## Diagnostic on the repository's registry dump

`docs/crosswalks/canonical_taxon_registry.csv` has 73,661 rows: 31,727 accepted and 41,934 synonym. The release behind this dump is not recorded in the file. Running `normalization_safe` over its `scientific_name` column, in this session:

| Finding | Count |
|---|---|
| Names that `canonical_name_of` collapses | **1,195** |
| …infraspecific (e.g. `Ophrys mammosa var. aegilica` → `Ophrys mammosa var`) | 806 |
| …hybrid (e.g. `Ophrys x breieri` → `Ophrys x`) | 279 |
| …other, mostly author particles (e.g. `Coelogyne acutilabium de Vogel` → `Coelogyne acutilabium de`) | 110 |
| Collapsed keys that still merge 2+ distinct names in the dump | 23 keys, 46 names (e.g. `Ophrys mammosa ssp. boissieri` / `ssp. mammosa`) |
| Rows whose stored `canonical_name` differs from today's `canonical_name_of` | 556 |

The registry builder discards later rows that share a key. The dump therefore cannot show how many taxa were dropped before export; the 23 merged keys are a lower bound.

A real mapping report still needs an `oc_graph.kg_nodes` taxon export, which is not in the repository. Run:

```bash
PYTHONPATH=. python scripts/build_taxon_graph_mapping.py \
  --load-rows load.csv --synonym-rows synonyms.csv \
  --graph-nodes kg_taxon_nodes.csv --release-label "<World Plants release>" \
  --output taxon_graph_mapping.json
```

The report records input SHA-256 hashes, per-status and per-reason counts, and every link with its candidate node keys for human review.
