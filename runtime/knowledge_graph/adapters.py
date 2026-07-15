"""Domain adapters for the unified Knowledge Graph build.

Every adapter maps rows from a domain's canonical relational source to graph
:class:`NodeSpec` / :class:`EdgeSpec` values, reusing the existing publisher
contract.  Nothing here is genus-specific and no adapter duplicates the
repository, publisher, quality or vocabulary infrastructure — they only supply
the domain-specific row->spec mapping.

Design rules (kept deliberately strict):

* An adapter emits the *domain* node (image, occurrence, trait, ...) and a
  single evidence-linked edge from the taxon it attaches to.
* An adapter NEVER emits a ``taxon`` node.  Taxonomy is already published; a
  taxon node's identity/label must not be overwritten by a domain build.  Edges
  reference the existing taxon via its canonical key ``taxon:<taxon_pk>`` and
  the publisher resolves it against the current graph.
* Node/edge types are drawn from the controlled vocabulary; unknown types are
  rejected by the publisher.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from .publisher import DomainAdapter, EdgeSpec, NodeSpec, canonical_key

TAXON_NODE_TYPE = "taxon"


def _label(row: dict[str, Any], fields: tuple[str, ...], fallback_prefix: str) -> str:
    for f in fields:
        val = row.get(f)
        if val:
            return str(val)
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
    """Build a standard taxon->domain-object adapter.

    Rows must provide ``source_pk`` (domain object id) and ``taxon_pk`` (the
    taxon to attach to).  Rows missing either are skipped (they surface as
    ``edge_missing_endpoint``/absent nodes and are reported by validation).
    """

    def produce(rows: Iterable[dict[str, Any]]) -> tuple[list[NodeSpec], list[EdgeSpec]]:
        nodes: list[NodeSpec] = []
        edges: list[EdgeSpec] = []
        seen_nodes: set[str] = set()
        for row in rows:
            source_pk = row.get("source_pk")
            taxon_pk = row.get("taxon_pk")
            if source_pk is None or taxon_pk is None:
                continue
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
                    payload={f: row[f] for f in payload_fields if f in row},
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

    return DomainAdapter(domain=domain, source_table=source_table, produce=produce)


IMAGES_ADAPTER = _make_adapter(
    domain="media", node_type="image", edge_type="has_image",
    source_table="oc_api.species_media_gallery_v1",
    label_fields=("caption", "scientific_name"),
    payload_fields=("media_url", "thumbnail_url", "media_type", "license",
                    "rights_holder", "source_name"),
)

OCCURRENCES_ADAPTER = _make_adapter(
    domain="occurrences", node_type="occurrence", edge_type="occurs_at",
    source_table="oc_atlas.occurrences",
    label_fields=("locality", "scientific_name"),
    payload_fields=("latitude", "longitude", "elevation", "country",
                    "event_date", "basis_of_record", "source_name"),
)

TRAITS_ADAPTER = _make_adapter(
    domain="traits", node_type="trait", edge_type="has_trait",
    source_table="oc_views.trait_resolved_v4",
    label_fields=("trait_name",),
    payload_fields=("trait_value", "support_count"),
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
    domain="conservation", node_type="conservation_assessment",
    edge_type="has_conservation_assessment",
    source_table="oc_conservation.conservation_records",
    label_fields=("iucn_category", "scientific_name"),
    payload_fields=("cites_appendix", "population_trend", "assessment_year",
                    "region", "source_name"),
)

CLIMATE_ADAPTER = _make_adapter(
    domain="climate", node_type="climate", edge_type="experiences_climate",
    source_table="oc_env_intel.species_environment_profile",
    label_fields=("environmental_readiness_label", "scientific_name"),
    payload_fields=("climate_proxy_zones", "avg_elevation_m", "min_elevation_m",
                    "max_elevation_m"),
)

LITERATURE_ADAPTER = _make_adapter(
    domain="literature", node_type="publication", edge_type="documented_by",
    source_table="oc_graph.taxon_literature_edges",
    label_fields=("title",),
    payload_fields=("doi", "year", "edge_strength"),
)


# Pipeline order matches the BUILD-060 specification.
DOMAIN_ADAPTERS: tuple[DomainAdapter, ...] = (
    OCCURRENCES_ADAPTER,
    TRAITS_ADAPTER,
    POLLINATORS_ADAPTER,
    MYCORRHIZA_ADAPTER,
    CONSERVATION_ADAPTER,
    CLIMATE_ADAPTER,
    LITERATURE_ADAPTER,
    IMAGES_ADAPTER,
)


def adapters_by_domain() -> dict[str, DomainAdapter]:
    return {a.domain: a for a in DOMAIN_ADAPTERS}
