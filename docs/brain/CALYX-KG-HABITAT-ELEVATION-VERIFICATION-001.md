# CALYX-KG-HABITAT-ELEVATION-VERIFICATION-001

## Decision

Promote habitat and elevation from fail-closed placeholders to verified live-source materialization paths inside PR #901, without mutating the production Knowledge Graph.

## Production catalog evidence

Read-only Render/PostgreSQL catalog inspection on 2026-08-12 established these current production relations and identifiers:

- `public.oc_species_habitat_claims`
  - canonical taxon link: `taxonomy_id`
  - row identity: `claim_id`
  - scientific content includes `habitat_class`, `habitat_text`, `elevation_min`, `elevation_max`, `climate_zone`, `substrate`, `canopy_cover`, `moisture_regime`
  - provenance/review content includes `source_type`, `source_id`, `source_table`, `source_column`, `citation_url`, `citation_text`, `evidence_text`, `observed_inferred_heuristic`, `confidence_score_numeric`, `claim_status`, `needs_review`, `review_status`

- `public.species_elevation_profile`
  - canonical taxon link and row identity: `accepted_taxon_id`
  - derived occurrence profile includes `n_records`, minimum/maximum/mean elevation, percentile elevations, standard deviation, genus/species labels, and timestamps

Both sources can be joined directly to `oc_graph.kg_nodes.source_pk` for active `node_type='taxon'` nodes. No fuzzy name mapping is required.

## Graph semantics

Habitat claim rows materialize as `habitat` nodes linked from canonical taxa with `occupies_habitat`. The node payload retains habitat/environmental qualifiers and source/review provenance so a habitat assertion is not separated from its evidentiary status.

Species elevation profiles materialize as `elevation` nodes linked from canonical taxa with `has_elevation`. These nodes are explicitly labelled `derived_occurrence_profile`; they must remain distinguishable from raw occurrence-level altitude observations. Raw occurrence elevations remain attached to occurrence evidence records.

This two-level representation supports queries such as taxa in a country within an altitude range while preserving the distinction between an individual observation and a derived species-level envelope.

## Governance

The verified projections are SELECT-only and pass through the existing SQL-safety validator. Production publication remains separately gated by explicit domains, `execute=True`, the exact confirmation token, single-writer locking, graph validation, and all-or-nothing rollback.

No production graph mutation occurred in this implementation pass.

## Validation boundary

Focused regression coverage now requires habitat/elevation projections to use the verified live relations and requires the materialization selector to admit those two domains while still refusing unverified geography/evidence domains.

GitHub-hosted CI has repeatedly returned zero-step jobs (`steps: null`), which is infrastructure non-execution rather than executable test evidence. Exact-head executable validation remains required before publication.
