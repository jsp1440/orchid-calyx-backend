"""Controlled vocabulary for the Orchid Continuum scientific Knowledge Graph.

Node types and edge types are grouped into scientific *domains* so that a
traversal can report domain coverage and explicit data gaps.  The existing
production graph (``oc_graph.kg_nodes`` / ``oc_graph.kg_edges``) currently
only populates the ``taxonomy`` domain (node types ``genus``/``taxon`` and
edge types ``genus_contains_species``/``species_belongs_to_genus``).

The additional node/edge types below are the canonical labels the graph
publisher emits when a domain's relational source is ingested.  Nothing here
is genus-specific; the vocabulary is reused for every taxon.
"""

from __future__ import annotations

NODE_TYPE_DOMAIN: dict[str, str] = {
    "genus": "taxonomy",
    "taxon": "taxonomy",
    "species": "taxonomy",
    "synonym": "taxonomy",
    "taxon_concept": "taxonomy",
    "image": "media",
    "occurrence": "occurrences",
    "place": "geography",
    "country": "geography",
    "region": "geography",
    "habitat": "habitat",
    "climate": "climate",
    "elevation": "elevation",
    "trait": "traits",
    "glossary_term": "glossary",
    "publication": "literature",
    "assertion": "evidence",
    "evidence": "evidence",
    "pollinator": "pollinators",
    "fungus": "mycorrhiza",
    "conservation_assessment": "conservation",
    "molecular_record": "molecular",
    "research_question": "research",
    "hypothesis": "research",
    "lesson": "education",
    "chapter": "education",
    "figure": "education",
}

EDGE_TYPE_DOMAIN: dict[str, str] = {
    "genus_contains_species": "taxonomy",
    "species_belongs_to_genus": "taxonomy",
    "has_synonym": "taxonomy",
    "has_taxon_concept": "taxonomy",
    "has_image": "media",
    "occurs_at": "occurrences",
    "occurs_in": "geography",
    "occupies_habitat": "habitat",
    "experiences_climate": "climate",
    "has_elevation": "elevation",
    "has_trait": "traits",
    "defined_by_term": "glossary",
    "documented_by": "literature",
    "supported_by_evidence": "evidence",
    "contradicted_by": "evidence",
    "associated_with_pollinator": "pollinators",
    "associated_with_mycorrhiza": "mycorrhiza",
    "has_conservation_assessment": "conservation",
    "has_molecular_record": "molecular",
    "phylogenetically_related_to": "molecular",
    "explained_by": "education",
    "raises_question": "research",
    "tested_by_hypothesis": "research",
}

ALL_DOMAINS: tuple[str, ...] = (
    "taxonomy", "media", "occurrences", "geography", "habitat", "climate",
    "elevation", "traits", "glossary", "literature", "evidence",
    "pollinators", "mycorrhiza", "conservation", "molecular", "research",
    "education",
)


def domain_for_node_type(node_type: str) -> str:
    return NODE_TYPE_DOMAIN.get(node_type, "unknown")


def domain_for_edge_type(edge_type: str) -> str:
    return EDGE_TYPE_DOMAIN.get(edge_type, "unknown")
