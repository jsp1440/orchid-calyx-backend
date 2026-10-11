# OC-EXTERNAL-SOURCE-REGISTRY-INTEGRATION

Integration of the 25-source Orchid Continuum Scientific Source Registry
(artifact v1.0.0, generated 2026-10-10) into the **existing** scientific
source infrastructure. No duplicate registry, no new ingestion system.

## What was added

| Path | Purpose |
| --- | --- |
| `app/scientific_adapter_lab/external_source_registry.py` | Integration module: artifact loading/validation, source-ID reconciliation, fail-closed ingestion gating, module-to-source lookup, backbone preservation, reporting |
| `app/scientific_adapter_lab/data/orchid_continuum_source_registry.json` | Bundled artifact (25 sources, 22 fields each) |
| `app/scientific_adapter_lab/data/orchid_continuum_source_registry.csv` | Flattened export of the same artifact |
| `tests/test_external_source_registry_integration.py` | 51 tests: validation, reconciliation, license gating, module lookup, backbone preservation, ingestion-interface compatibility, federation alignment |

## Reuse, not duplication

- **Provider definitions** — reconciliation entries map external source IDs
  onto the existing `SOURCE_CANDIDATES` in
  `app/scientific_adapter_lab/source_discovery_registry.py`
  (`oc-source-discovery-registry/v1`): inat → `inat_pollination`,
  gbif → `gbif_occurrence`, bhl → `bhl`, idigbio → `idigbio`,
  globi → `globi_pollination`, unite → `unite_its`, try → `try_traits`,
  powo → `pow_kew`, europepmc → `europepmc`. Sources without an existing
  candidate are *projected* into the existing registry's decision vocabulary
  (`ADD` at bounded priority for eligible sources, `DEFER` with recorded
  blockers otherwise) — never duplicated.
- **Ingestion adapters** — reconciliation points at the existing adapters:
  `harvesters/inat.py`, `harvesters/gbif_api.py`, `harvesters/gbif_global_api.py`,
  `harvesters/traitbank.py`, `runtime/interaction_harvester.py`,
  `runtime/globi_canonical_harvester.py`, `runtime/literature_harvester.py`,
  `app/harvest/plugins/bhl/client.py`.
- **Rights model** — gating mirrors `app/source_federation/inventory.py`
  fail-closed semantics (`RightsState` open/restricted/unknown).

## Ingestion gates (fail-closed)

| Gate | Count | Sources |
| --- | --- | --- |
| ELIGIBLE | 9 | unite, wcvp, ipni, col, ncbi_taxonomy, openalex, plant_ontology, darwin_core, wikidata |
| CONDITIONAL | 10 | inat, gbif, bhl, idigbio, globi, eol_traitbank, powo, wfo, crossref, wikimedia_commons |
| BLOCKED | 6 | iucn, speciesplus, plazi, europepmc, gnverifier, try |

- **BLOCKED** — `partially_verified` and `needs_manual_review` sources
  (Species+, Plazi, Europe PMC, GNVerifier, TRY) plus IUCN (Terms of Use, no
  CC license, commercial use strictly forbidden). Automated ingestion stays
  blocked until permissions are established. Blocked sources remain *visible*
  in module lookups so modules can surface them as pending-permission.
- **CONDITIONAL** — per-record/per-dataset licensing; not cleared for new
  automated ingestion, but existing adapters continue under their current
  reviewed scope (they already surface per-record license/attribution fields).
- **ELIGIBLE** — verified status and cleanly stated open licensing.
- Unknown source IDs and unknown verification statuses fail closed to BLOCKED.

## Module bindings

Lexicon → `app/lexicon` · Illustrated Glossary →
`app/scientific_adapter_lab/glossary_intake_bridge.py` · Literature Extraction →
`app/literature_extraction` · Species Dossiers → `app/species_dossier` ·
Matrix → `runtime/matrix_identification.py`

## Taxonomic backbone

World Plants (Dr. Michael Hassler) remains the canonical taxonomic authority
(`runtime/knowledge_graph/canonical_taxonomy.py`, BUILD-065 owner decision).
POWO, WCVP, IPNI, WFO, COL and NCBI are **authority mappings only**;
`assert_backbone_preserved()` raises `BackboneViolationError` if any source
claims a canonical-backbone role. WCVP never silently replaces World Plants.

## Governance invariants

`graph_mutation: False` · `automatic_publication: False` · no production
writes · no scraping against terms · provenance, citations, evidence URLs and
attribution requirements carried through every reconciled record.

## Verification

`pytest tests/test_external_source_registry_integration.py` — 51 passed.
