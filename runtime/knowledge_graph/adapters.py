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
    source_table="oc_core.media_assets",
    label_fields=("title", "caption", "filename"),
    payload_fields=("url", "mime_type", "width", "height", "phenotype_tags"),
)

OCCURRENCES_ADAPTER = _make_adapter(
    domain="occurrences", node_type="occurrence", edge_type="occurs_at",
    source_table="oc_atlas.occurrences",
    label_fields=("locality", "site_name"),
    payload_fields=("latitude", "longitude", "event_date", "recorded_by", "dataset"),
)

TRAITS_ADAPTER = _make_adapter(
    domain="traits", node_type="trait", edge_type="has_trait",
    source_table="oc_traits.traits",
    label_fields=("trait_name", "trait_label"),
    payload_fields=("trait_value", "unit", "method", "trait_key"),
)

POLLINATORS_ADAPTER = _make_adapter(
    domain="pollinators", node_type="pollinator", edge_type="associated_with_pollinator",
    source_table="oc_pollination.interactions",
    label_fields=("pollinator_name", "interactor_name"),
    payload_fields=("interaction_type", "source_dataset"),
)

MYCORRHIZA_ADAPTER = _make_adapter(
    domain="mycorrhiza", node_type="fungus", edge_type="associated_with_mycorrhiza",
    source_table="oc_mycorrhiza.associations",
    label_fields=("fungus_name", "fungal_taxon"),
    payload_fields=("association_type", "source_dataset"),
)

CONSERVATION_ADAPTER = _make_adapter(
    domain="conservation", node_type="conservation_assessment",
    edge_type="has_conservation_assessment",
    source_table="oc_conservation.conservation_records",
    label_fields=("status_label", "category"),
    payload_fields=("status_code", "assessment_year", "authority", "criteria"),
)

CLIMATE_ADAPTER = _make_adapter(
    domain="climate", node_type="climate", edge_type="experiences_climate",
    source_table="oc_env.climate_summaries",
    label_fields=("climate_label", "koppen_class"),
    payload_fields=("temp_mean_c", "precip_mm", "elevation_m", "source_layer"),
)

LITERATURE_ADAPTER = _make_adapter(
    domain="literature", node_type="publication", edge_type="documented_by",
    source_table="oc_citations.literature_nodes",
    label_fields=("citation", "title"),
    payload_fields=("doi", "year", "authors", "journal"),
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
