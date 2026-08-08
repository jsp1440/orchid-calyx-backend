"""Controlled vocabulary for the Orchid Continuum scientific Knowledge Graph.

Node types and edge types are grouped into scientific *domains* so that a
traversal can report domain coverage and explicit data gaps. The original
production graph was taxon-centered; the causal-reasoning vocabulary extends
that model across molecular biology, anatomy, physiology, development,
environment, phenotype, cultivation, and biotic interactions.

Nothing in this vocabulary publishes scientific claims. It defines canonical
labels and domain assignments that publishers and validators may accept.
"""

from __future__ import annotations

from .causal_vocabulary import (
    CANONICAL_CAUSAL_EDGE_TYPES,
    CAUSAL_EVIDENCE_EDGE_TYPES,
    CAUSAL_NODE_TYPE_DOMAIN,
)

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
    **CAUSAL_NODE_TYPE_DOMAIN,
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

# Extend rather than overwrite the legacy domain assignment of evidence aliases
# such as ``documented_by`` and ``supported_by_evidence``.
for _edge_type in CANONICAL_CAUSAL_EDGE_TYPES:
    EDGE_TYPE_DOMAIN.setdefault(_edge_type, "causal_reasoning")
for _edge_type in CAUSAL_EVIDENCE_EDGE_TYPES:
    EDGE_TYPE_DOMAIN.setdefault(_edge_type, "evidence")

ALL_DOMAINS: tuple[str, ...] = (
    "taxonomy",
    "media",
    "occurrences",
    "geography",
    "habitat",
    "climate",
    "elevation",
    "traits",
    "glossary",
    "literature",
    "evidence",
    "pollinators",
    "mycorrhiza",
    "conservation",
    "molecular",
    "research",
    "education",
    "anatomy",
    "physiology",
    "development",
    "phenotype",
    "environment",
    "cultivation",
    "biotic_interactions",
    "causal_reasoning",
)


def domain_for_node_type(node_type: str) -> str:
    return NODE_TYPE_DOMAIN.get(node_type, "unknown")


def domain_for_edge_type(edge_type: str) -> str:
    return EDGE_TYPE_DOMAIN.get(edge_type, "unknown")
