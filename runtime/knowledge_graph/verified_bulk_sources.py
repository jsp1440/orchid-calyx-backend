"""Verified read-only projections for the live bulk scientific corpora.

These projections are intentionally separate from the legacy source registry until
current-main can absorb the production-schema correction cleanly.  They were
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
}


for _domain, _sql in BULK_SOURCE_QUERIES.items():
    try:
        assert_safe_sql(_sql)
    except Exception as exc:  # pragma: no cover - import-time invariant
        raise RuntimeError(f"unsafe bulk graph source projection: {_domain}") from exc


def bulk_verified_queries() -> dict[str, str]:
    """Return a defensive copy of verified live bulk source projections."""
    return dict(BULK_SOURCE_QUERIES)
