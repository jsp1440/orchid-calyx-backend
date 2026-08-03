"""Domain adapters for the unified Knowledge Graph build.

Every adapter maps rows from a domain's canonical relational source to graph
NodeSpec / EdgeSpec values. Adapters emit domain objects and taxon-linked edges;
they never overwrite canonical taxonomy nodes.
"""

from __future__ import annotations

from typing import Any, Iterable

from .publisher import DomainAdapter, EdgeSpec, NodeSpec, canonical_key

TAXON_NODE_TYPE = "taxon"


def _label(row: dict[str, Any], fields: tuple[str, ...], fallback_prefix: str) -> str:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return str(value)
    return f"{fallback_prefix}:{row.get('source_pk')}"


def _make_adapter(
    *,
    domain: str,
    node_type: str,
    edge_type: str,
    source_table: str,
    label_fields: tuple[str, ...],
    payload_fields: tuple[str, ...],
) -> DomainAdapter:
    def produce(rows: Iterable[dict[str, Any]]) -> tuple[list[NodeSpec], list[EdgeSpec]]:
        nodes: list[NodeSpec] = []
        edges: list[EdgeSpec] = []
        seen_nodes: set[str] = set()
        for row in rows:
            source_pk = row.get("source_pk")
            taxon_pk = row.get("taxon_pk")
            if source_pk is None or taxon_pk is None:
                raise ValueError(
                    f"{domain} adapter received a row without source_pk/taxon_pk"
                )
            key = canonical_key(node_type, source_pk)
            if key not in seen_nodes:
                seen_nodes.add(key)
                nodes.append(NodeSpec(
                    node_type=node_type,
                    source_pk=source_pk,
                    display_label=_label(row, label_fields, node_type),
                    source_table=source_table,
                    evidence_class=row.get("evidence_class"),
                    confidence_score=row.get("confidence_score"),
                    confidence_label=row.get("confidence_label"),
                    payload={field: row[field] for field in payload_fields if field in row},
                ))
            edges.append(EdgeSpec(
                edge_type=edge_type,
                from_key=canonical_key(TAXON_NODE_TYPE, taxon_pk),
                to_key=key,
                source_table=source_table,
                source_pk=source_pk,
                evidence_class=row.get("evidence_class"),
                confidence_score=row.get("confidence_score"),
                confidence_label=row.get("confidence_label"),
                rule_name=f"{domain}_build",
                payload={},
            ))
        return nodes, edges

    return DomainAdapter(
        domain=domain,
        source_table=source_table,
        produce=produce,
        required_identifiers=("source_pk", "taxon_pk"),
    )


IMAGES_ADAPTER = _make_adapter(
    domain="media", node_type="image", edge_type="has_image",
    source_table="oc_api.species_media_gallery_v1",
    label_fields=("caption", "scientific_name"),
    payload_fields=("media_url", "thumbnail_url", "media_type", "license", "rights_holder", "source_name"),
)
OCCURRENCES_ADAPTER = _make_adapter(
    domain="occurrences", node_type="occurrence", edge_type="occurs_at",
    source_table="oc_atlas.occurrences",
    label_fields=("locality", "scientific_name"),
    payload_fields=("latitude", "longitude", "elevation", "country", "event_date", "basis_of_record", "source_name"),
)
GEOGRAPHY_ADAPTER = _make_adapter(
    domain="geography", node_type="place", edge_type="occurs_in",
    source_table="oc_geo.taxon_places",
    label_fields=("place_name", "country", "region"),
    payload_fields=("country", "region", "locality", "latitude", "longitude", "geographic_scope"),
)
HABITAT_ADAPTER = _make_adapter(
    domain="habitat", node_type="habitat", edge_type="occupies_habitat",
    source_table="oc_habitat.taxon_habitats",
    label_fields=("habitat_name", "habitat_type"),
    payload_fields=("habitat_type", "biome", "substrate", "description", "source_name"),
)
CLIMATE_ADAPTER = _make_adapter(
    domain="climate", node_type="climate", edge_type="experiences_climate",
    source_table="oc_env_intel.species_environment_profile",
    label_fields=("environmental_readiness_label", "scientific_name"),
    payload_fields=("climate_proxy_zones", "avg_elevation_m", "min_elevation_m", "max_elevation_m"),
)
ELEVATION_ADAPTER = _make_adapter(
    domain="elevation", node_type="elevation", edge_type="has_elevation",
    source_table="oc_env.taxon_elevation_profiles",
    label_fields=("elevation_label", "scientific_name"),
    payload_fields=("minimum_elevation_m", "maximum_elevation_m", "mean_elevation_m", "method", "source_name"),
)
TRAITS_ADAPTER = _make_adapter(
    domain="traits", node_type="trait", edge_type="has_trait",
    source_table="oc_views.trait_resolved_v4",
    label_fields=("trait_name",),
    payload_fields=("trait_value", "support_count"),
)
GLOSSARY_ADAPTER = _make_adapter(
    domain="glossary", node_type="glossary_term", edge_type="defined_by_term",
    source_table="oc_glossary.taxon_terms",
    label_fields=("term", "preferred_label"),
    payload_fields=("definition", "scope_note", "source_name"),
)
LITERATURE_ADAPTER = _make_adapter(
    domain="literature", node_type="publication", edge_type="documented_by",
    source_table="oc_graph.taxon_literature_edges",
    label_fields=("title",),
    payload_fields=("doi", "year", "edge_strength"),
)
EVIDENCE_ADAPTER = _make_adapter(
    domain="evidence", node_type="evidence", edge_type="supported_by_evidence",
    source_table="oc_claims.evidence_item",
    label_fields=("title", "evidence_type", "claim_label"),
    payload_fields=("claim_id", "evidence_type", "citation", "source_uri", "excerpt", "review_state"),
)
POLLINATORS_ADAPTER = _make_adapter(
    domain="pollinators", node_type="pollinator", edge_type="associated_with_pollinator",
    source_table="oc_interactions.orchid_interaction_edges",
    label_fields=("partner_taxon_name",),
    payload_fields=("interaction_type", "interaction_group", "evidence_citation"),
)
MYCORRHIZA_ADAPTER = _make_adapter(
    domain="mycorrhiza", node_type="fungus", edge_type="associated_with_mycorrhiza",
    source_table="oc_mycorrhiza.orchid_fungal_associations",
    label_fields=("fungal_name",),
    payload_fields=("association_type", "life_stage", "citation", "doi"),
)
CONSERVATION_ADAPTER = _make_adapter(
    domain="conservation", node_type="conservation_assessment", edge_type="has_conservation_assessment",
    source_table="oc_conservation.conservation_records",
    label_fields=("iucn_category", "scientific_name"),
    payload_fields=("cites_appendix", "population_trend", "assessment_year", "region", "source_name"),
)
MOLECULAR_ADAPTER = _make_adapter(
    domain="molecular", node_type="molecular_record", edge_type="has_molecular_record",
    source_table="oc_phylogeny.taxon_molecular_records",
    label_fields=("marker_name", "accession", "scientific_name"),
    payload_fields=("marker_name", "accession", "sequence_length", "tree_id", "source_name"),
)
EDUCATION_ADAPTER = _make_adapter(
    domain="education", node_type="lesson", edge_type="explained_by",
    source_table="ocu.taxon_learning_objects",
    label_fields=("title", "lesson_title", "figure_title"),
    payload_fields=("object_type", "title", "summary", "audience", "source_uri"),
)

DOMAIN_ADAPTERS: tuple[DomainAdapter, ...] = (
    OCCURRENCES_ADAPTER,
    GEOGRAPHY_ADAPTER,
    HABITAT_ADAPTER,
    CLIMATE_ADAPTER,
    ELEVATION_ADAPTER,
    TRAITS_ADAPTER,
    GLOSSARY_ADAPTER,
    LITERATURE_ADAPTER,
    EVIDENCE_ADAPTER,
    POLLINATORS_ADAPTER,
    MYCORRHIZA_ADAPTER,
    CONSERVATION_ADAPTER,
    MOLECULAR_ADAPTER,
    EDUCATION_ADAPTER,
    IMAGES_ADAPTER,
)


def adapters_by_domain() -> dict[str, DomainAdapter]:
    return {adapter.domain: adapter for adapter in DOMAIN_ADAPTERS}
