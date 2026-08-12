from app.literature_extraction.models import Entity
from runtime.knowledge_graph.biotic_relation_ontology import (
    GLOBI_RO_RELATIONS,
    normalize_biotic_relation,
)
from runtime.knowledge_graph.publication_eligible_paper_graph import (
    build_publication_eligible_paper_graph_specs,
)
from runtime.knowledge_graph.publisher import canonical_key
from runtime.knowledge_graph.vocabulary import domain_for_edge_type
from tests.test_publication_eligible_paper_graph import _paper, _prov


def test_globi_style_translation_is_controlled_and_fail_closed():
    relation = normalize_biotic_relation("visits flowers of")
    assert relation is not None
    assert relation.label == "visitsFlowersOf"
    assert relation.ro_uri == "http://purl.obolibrary.org/obo/RO_0002622"
    assert normalize_biotic_relation("possibly likes") is None
    assert GLOBI_RO_RELATIONS["pollinates"].endswith("RO_0002455")
    assert domain_for_edge_type("visitsFlowersOf") == "biotic_interactions"


def test_publication_eligible_taxon_claim_emits_ro_interaction_edge():
    paper = _paper()
    paper.entities.append(
        Entity(
            entity_id="taxon-2",
            entity_type="taxon",
            name="Apis mellifera",
            normalized_name="Apis mellifera",
            provenance=_prov("accepted"),
        )
    )
    claim = paper.claims[0]
    claim.subject_ids = ["taxon-2"]
    claim.object_ids = ["taxon-1"]
    claim.predicate = "visits flowers of"

    bee_key = canonical_key("taxon", 101)
    orchid_key = canonical_key("taxon", 42)
    bundle = build_publication_eligible_paper_graph_specs(
        paper,
        taxon_keys_by_entity_id={"taxon-1": orchid_key, "taxon-2": bee_key},
    )

    interaction_edges = [
        edge for edge in bundle.edges if edge.edge_type == "visitsFlowersOf"
    ]
    assert len(interaction_edges) == 1
    edge = interaction_edges[0]
    assert edge.from_key == bee_key
    assert edge.to_key == orchid_key
    assert edge.confidence_label == "publication_eligible"
    assert edge.rule_name == "paper_globi_ro_biotic_relation"
    assert edge.payload["ro_uri"].endswith("RO_0002622")
    assert edge.payload["verbatim_predicate"] == "visits flowers of"
    assert edge.payload["publication_eligible"] is True


def test_interaction_requires_publication_eligibility_and_exact_taxon_endpoints():
    paper = _paper()
    paper.claims[0].predicate = "pollinates"
    paper.claims[0].object_ids = ["taxon-2"]

    # Missing second exact canonical taxon endpoint: no biotic edge.
    bundle = build_publication_eligible_paper_graph_specs(
        paper,
        taxon_keys_by_entity_id={"taxon-1": canonical_key("taxon", 42)},
    )
    assert not any(edge.edge_type == "pollinates" for edge in bundle.edges)

    # Removing the explicit publication decision also fails closed.
    paper.publication_decisions = []
    bundle = build_publication_eligible_paper_graph_specs(
        paper,
        taxon_keys_by_entity_id={
            "taxon-1": canonical_key("taxon", 42),
            "taxon-2": canonical_key("taxon", 101),
        },
    )
    assert not any(edge.edge_type == "pollinates" for edge in bundle.edges)
