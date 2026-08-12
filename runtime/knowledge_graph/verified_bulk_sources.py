"""Verified read-only projections for the live bulk scientific corpora.

These projections are intentionally separate from the legacy source registry until
current-main can absorb the production-schema correction cleanly. They were
verified against the deployed PostgreSQL catalog on 2026-08-12.

The module contains SELECT-only SQL and performs no graph mutation.
"""

from __future__ import annotations

from .source_registry import assert_safe_sql


BULK_SOURCE_QUERIES: dict[str, str] = {
    "occurrences": """
        select o.occurrence_id as source_pk,
               o.taxonomy_id as taxon_pk,
               o.scientific_name,
               o.country,
               o.region,
               o.locality,
               o.decimal_latitude as latitude,
               o.decimal_longitude as longitude,
               o.elevation_meters as elevation,
               o.minimum_elevation,
               o.maximum_elevation,
               o.growth_habit,
               o.habitat_description,
               o.climate_preference,
               o.temperature_range,
               o.humidity_preference,
               o.source_table as source_name,
               o.source_table as evidence_class,
               o.source_record_id,
               o.raw_payload,
               o.created_at,
               o.updated_at
        from public.orchid_occurrence o
        where o.taxonomy_id is not null
          and exists (
              select 1
              from oc_graph.kg_nodes k
              where k.node_type = 'taxon'
                and k.source_pk = o.taxonomy_id::text
          )
    """,
    "traits": """
        select md5(
                   coalesce(t.accepted_taxon_id, t.taxon_id)::text || '|' ||
                   t.normalized_trait_name || '|' ||
                   coalesce(t.source_trait_value, '') || '|' ||
                   coalesce(t.source_pk_text, '')
               ) as source_pk,
               coalesce(t.accepted_taxon_id, t.taxon_id) as taxon_pk,
               t.normalized_trait_name as trait_name,
               t.source_trait_value as trait_value,
               t.normalized_trait_unit as trait_unit,
               1::integer as support_count,
               t.final_score as confidence_score,
               t.vocabulary_status as confidence_label,
               t.source_schema,
               t.source_table,
               t.source_pk_text,
               t.page_id,
               t.source_scientific_name,
               t.match_type,
               t.match_rank,
               t.match_confidence,
               t.candidate_count,
               t.source_weight,
               t.vocabulary_normalization_method
        from public.oc_trait_consensus_normalized t
        where coalesce(t.accepted_taxon_id, t.taxon_id) is not null
          and t.normalized_trait_name is not null
          and exists (
              select 1
              from oc_graph.kg_nodes k
              where k.node_type = 'taxon'
                and k.source_pk = coalesce(t.accepted_taxon_id, t.taxon_id)::text
          )
    """,
    "habitat": """
        select h.claim_id as source_pk,
               h.taxonomy_id as taxon_pk,
               h.habitat_class as habitat_name,
               h.habitat_class as habitat_type,
               h.climate_zone as biome,
               h.substrate,
               h.habitat_text as description,
               coalesce(h.source_type, h.source_table) as source_name,
               h.elevation_min,
               h.elevation_max,
               h.climate_zone,
               h.canopy_cover,
               h.moisture_regime,
               h.citation_url,
               h.citation_text,
               h.evidence_text,
               h.observed_inferred_heuristic as evidence_class,
               h.confidence_score_numeric as confidence_score,
               h.review_status as confidence_label,
               h.claim_status,
               h.needs_review,
               h.source_id,
               h.source_table,
               h.source_column,
               h.created_at,
               h.updated_at
        from public.oc_species_habitat_claims h
        where h.taxonomy_id is not null
          and h.claim_id is not null
          and exists (
              select 1
              from oc_graph.kg_nodes k
              where k.node_type = 'taxon'
                and k.source_pk = h.taxonomy_id::text
          )
    """,
    "elevation": """
        select e.accepted_taxon_id as source_pk,
               e.accepted_taxon_id as taxon_pk,
               concat_ws(' ', initcap(e.genus_lower), e.species_lower) as scientific_name,
               concat_ws('–', e.elev_min_m::text, e.elev_max_m::text) || ' m' as elevation_label,
               e.elev_min_m as minimum_elevation_m,
               e.elev_max_m as maximum_elevation_m,
               e.elev_mean_m as mean_elevation_m,
               'derived_from_occurrence_records'::text as method,
               'public.species_elevation_profile'::text as source_name,
               'derived_occurrence_profile'::text as evidence_class,
               e.n_records,
               e.elev_p05_m,
               e.elev_p25_m,
               e.elev_p50_m,
               e.elev_p75_m,
               e.elev_p95_m,
               e.elev_sd_m,
               e.created_at,
               e.updated_at
        from public.species_elevation_profile e
        where e.accepted_taxon_id is not null
          and exists (
              select 1
              from oc_graph.kg_nodes k
              where k.node_type = 'taxon'
                and k.source_pk = e.accepted_taxon_id::text
          )
    """,
}


for _domain, _sql in BULK_SOURCE_QUERIES.items():
    try:
        assert_safe_sql(_sql)
    except Exception as exc:  # pragma: no cover - import-time invariant
        raise RuntimeError(f"unsafe bulk graph source projection: {_domain}") from exc


def bulk_verified_queries() -> dict[str, str]:
    """Return a defensive copy of verified live bulk source projections."""
    return dict(BULK_SOURCE_QUERIES)
