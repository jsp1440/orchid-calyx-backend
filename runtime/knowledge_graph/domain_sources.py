"""Canonical relational sources per scientific domain (audit result).

This registry is the *contract* between the relational warehouse and the graph
publisher.  It records, for each domain, the canonical production source table
(or view) verified to exist in the Orchid Continuum database, and the graph
node/edge vocabulary the publisher would emit.  It is descriptive metadata used
by the report and by future build runs; importing it performs no I/O.

Status values:
  production   — verified production data exists; safe to publish as graph evidence
  staging_only — data exist but only in staging; must NOT be published as prod evidence
  unavailable  — no usable source located
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DomainSource:
    domain: str
    status: str
    source: str | None
    node_type: str | None
    edge_type: str | None
    note: str = ""


# Verified against oc_* schemas in the Orchid Continuum (Neon) database.
DOMAIN_SOURCES: tuple[DomainSource, ...] = (
    DomainSource("taxonomy", "production", "oc_graph.kg_nodes/kg_edges", "taxon",
                 "genus_contains_species", "Already published to the graph."),
    DomainSource("media", "production", "oc_core.media_assets + oc_core.record_media_link",
                 "image", "has_image", "Also oc_api.species_media_gallery_v1 for gallery."),
    DomainSource("occurrences", "production", "oc_atlas.occurrences (oc_views.occurrences_enriched)",
                 "occurrence", "occurs_at", ""),
    DomainSource("geography", "production", "oc_geo.* / oc_regions.*", "place", "occurs_in", ""),
    DomainSource("habitat", "production", "oc_habitat.*", "habitat", "occupies_habitat", ""),
    DomainSource("climate", "production", "oc_env.* / oc_env_intel.*", "climate", "experiences_climate", ""),
    DomainSource("elevation", "production", "oc_dependency.elevation_derivation_queue / oc_env.*",
                 "elevation", "has_elevation", "Verify derivation completeness before publishing."),
    DomainSource("traits", "production", "oc_traits.traits (oc_views.trait_resolved_v4)",
                 "trait", "has_trait", "Prefer resolved/consensus views over raw."),
    DomainSource("glossary", "production", "oc_glossary.* / oc_zoo.glossary_terms",
                 "glossary_term", "defined_by_term", ""),
    DomainSource("literature", "production",
                 "oc_citations.canonical_taxon_literature_edges + literature_nodes",
                 "publication", "documented_by", "oc_graph.taxon_literature_edges also present."),
    DomainSource("evidence", "production",
                 "oc_claims.evidence_item + claim_evidence_link",
                 "evidence", "supported_by_evidence",
                 "Model claims as assertion/evidence nodes, not raw edges."),
    DomainSource("pollinators", "production", "oc_pollination.* / oc_globi.* / oc_interactions.*",
                 "pollinator", "associated_with_pollinator", ""),
    DomainSource("mycorrhiza", "production",
                 "oc_mycorrhiza.* / oc_dependency.fungal_dependency_evidence",
                 "fungus", "associated_with_mycorrhiza", ""),
    DomainSource("conservation", "production", "oc_conservation.conservation_records",
                 "conservation_assessment", "has_conservation_assessment", ""),
    DomainSource("molecular", "production", "oc_phylogeny.*", "molecular_record",
                 "phylogenetically_related_to", "Verify per-taxon coverage before publishing."),
    DomainSource("research", "staging_only", "oc_reasoning.* / oc_reflect.*",
                 "research_question", "raises_question",
                 "Treat as staging until promoted; do not publish as prod evidence."),
    DomainSource("education", "production", "oc_story.* / oc_figures.* / ocu.*",
                 "lesson", "explained_by", "Knowledge Objects: lessons/chapters/figures."),
)


def by_domain() -> dict[str, DomainSource]:
    return {d.domain: d for d in DOMAIN_SOURCES}
