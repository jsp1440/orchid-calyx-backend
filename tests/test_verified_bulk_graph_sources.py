from runtime.knowledge_graph.adapters import (
    ELEVATION_ADAPTER,
    HABITAT_ADAPTER,
    OCCURRENCES_ADAPTER,
    TRAITS_ADAPTER,
)
from runtime.knowledge_graph.production_materializer import _selected_queries, select_domains
from runtime.knowledge_graph.source_registry import assert_safe_sql
from runtime.knowledge_graph.verified_bulk_sources import bulk_verified_queries


def test_bulk_source_queries_are_safe_and_use_live_production_corpora():
    queries = bulk_verified_queries()
    assert set(queries) == {"occurrences", "traits", "habitat", "elevation"}
    for sql in queries.values():
        assert_safe_sql(sql)

    occurrence_sql = queries["occurrences"]
    assert "from public.orchid_occurrence" in occurrence_sql.lower()
    assert "o.taxonomy_id as taxon_pk" in occurrence_sql.lower()
    assert "o.decimal_latitude as latitude" in occurrence_sql.lower()
    assert "o.decimal_longitude as longitude" in occurrence_sql.lower()
    assert "o.elevation_meters as elevation" in occurrence_sql.lower()
    assert "o.minimum_elevation" in occurrence_sql.lower()
    assert "o.maximum_elevation" in occurrence_sql.lower()

    trait_sql = queries["traits"]
    assert "from public.oc_trait_consensus_normalized" in trait_sql.lower()
    assert "normalized_trait_name as trait_name" in trait_sql.lower()
    assert "source_trait_value as trait_value" in trait_sql.lower()
    assert "coalesce(t.accepted_taxon_id, t.taxon_id) as taxon_pk" in trait_sql.lower()

    habitat_sql = queries["habitat"]
    assert "from public.oc_species_habitat_claims" in habitat_sql.lower()
    assert "h.taxonomy_id as taxon_pk" in habitat_sql.lower()
    assert "h.habitat_class as habitat_type" in habitat_sql.lower()
    assert "h.evidence_text" in habitat_sql.lower()
    assert "h.review_status as confidence_label" in habitat_sql.lower()

    elevation_sql = queries["elevation"]
    assert "from public.species_elevation_profile" in elevation_sql.lower()
    assert "e.accepted_taxon_id as taxon_pk" in elevation_sql.lower()
    assert "e.elev_min_m as minimum_elevation_m" in elevation_sql.lower()
    assert "e.elev_max_m as maximum_elevation_m" in elevation_sql.lower()
    assert "e.elev_mean_m as mean_elevation_m" in elevation_sql.lower()


def test_materializer_overrides_legacy_registry_queries_with_verified_live_sources():
    selection = select_domains(("occurrences", "traits", "habitat", "elevation"))
    assert selection.valid
    queries = _selected_queries(selection)
    assert "public.orchid_occurrence" in queries["occurrences"]
    assert "oc_atlas.occurrences" not in queries["occurrences"]
    assert "public.oc_trait_consensus_normalized" in queries["traits"]
    assert "oc_views.trait_resolved_v4" not in queries["traits"]
    assert "public.oc_species_habitat_claims" in queries["habitat"]
    assert "public.species_elevation_profile" in queries["elevation"]


def test_adapters_identify_verified_live_sources_for_graph_provenance():
    assert OCCURRENCES_ADAPTER.source_table == "public.orchid_occurrence"
    assert TRAITS_ADAPTER.source_table == "public.oc_trait_consensus_normalized"
    assert HABITAT_ADAPTER.source_table == "public.oc_species_habitat_claims"
    assert ELEVATION_ADAPTER.source_table == "public.species_elevation_profile"


def test_habitat_and_elevation_are_selectable_without_enabling_unverified_domains():
    selection = select_domains(("habitat", "elevation"))
    assert selection.requested == ("habitat", "elevation")
    assert selection.selected == ("habitat", "elevation")
    assert selection.unavailable == ()

    unavailable = select_domains(("geography", "evidence"))
    assert unavailable.selected == ()
    assert unavailable.unavailable == ("geography", "evidence")
