from __future__ import annotations

from app.trait_genomics.evidence_router import ScientificEvidenceRouter
from app.trait_genomics.evidence_routing_service import LiteratureEvidenceRoutingService
from app.trait_genomics.molecular_harvester import MolecularHarvestTarget


class FakeClient:
    def __init__(self, articles, annotations_by_id=None):
        self.articles = list(articles)
        self.annotations_by_id = annotations_by_id or {}

    def search(self, scientific_name: str, *, page_size: int):
        return list(self.articles)[:page_size]

    def annotations(self, article_id: str):
        return list(self.annotations_by_id.get(article_id, []))

    def retrieval_diagnostics(self):
        return {"adaptive_retrieval": True, "queries_executed": 1}


class FakeRepository:
    def __init__(self):
        self.rows = []

    def upsert(self, row):
        self.rows.append(dict(row))
        return dict(row)


def target():
    return MolecularHarvestTarget(
        canonical_taxon_id="52090",
        scientific_name="Dendrobium cuthbertsonii",
    )


def annotation(name="MYB1"):
    return {
        "exact": name,
        "type": "Gene_Proteins",
        "provider": "Europe PMC",
        "tags": [{"name": name, "uri": "https://identifiers.org/ncbigene:123"}],
    }


def test_router_classifies_phylogenetic_sequence_context():
    routed = ScientificEvidenceRouter().route(
        {
            "title": "Molecular phylogeny of Dendrobium using ITS and matK sequences",
            "abstractText": "Plastid matK and nuclear ITS sequences resolved phylogenetic relationships.",
        },
        has_gene_annotations=False,
        molecular_candidate_count=0,
    )
    assert routed.route == "phylogenetic_sequence_context"
    assert routed.confidence >= 0.8


def test_router_classifies_trait_morphology_without_promoting_molecular_association():
    routed = ScientificEvidenceRouter().route(
        {
            "title": "Labellum micromorphology in Dendrobium",
            "abstractText": "Floral morphology and labellum characters were compared across species.",
        },
        has_gene_annotations=True,
        molecular_candidate_count=0,
    )
    assert routed.route == "trait_morphology_evidence"
    assert "gene_annotations_present_but_no_strict_association" in routed.reasons


def test_title_level_micromorphology_beats_secondary_phylogenetic_method_context():
    routed = ScientificEvidenceRouter().route(
        {
            "title": "Micromorphology of Labellum in Selected Dendrobium spp.",
            "abstractText": (
                "Labellum micromorphology was compared among selected species, and nuclear ITS "
                "sequences were used to provide phylogenetic context."
            ),
        },
        has_gene_annotations=False,
        molecular_candidate_count=0,
        full_text_available=True,
    )
    assert routed.route == "trait_morphology_evidence"
    assert routed.confidence == 0.9
    assert "title_level_morphology_signal" in routed.reasons
    assert "phylogenetic_sequence_context" in routed.secondary_routes


def test_router_prioritizes_strict_molecular_candidate():
    routed = ScientificEvidenceRouter().route(
        {
            "title": "Flower color genetics in orchids",
            "abstractText": "Expression of MYB1 was associated with flower color.",
        },
        has_gene_annotations=True,
        molecular_candidate_count=1,
    )
    assert routed.route == "molecular_association_candidate"
    assert routed.confidence == 0.95


def test_routing_service_is_read_only_by_default_and_preserves_routes():
    articles = [
        {
            "pmid": "1",
            "pmcid": "PMC1",
            "title": "Molecular phylogeny of Dendrobium using ITS and matK",
            "abstractText": "ITS and matK sequences were used for phylogenetic reconstruction.",
            "_calyx_retrieval_strategy": "tokenized_taxon_molecular",
            "_calyx_retrieval_query": "Dendrobium cuthbertsonii",
        },
        {
            "pmid": "2",
            "title": "Labellum micromorphology of Dendrobium",
            "abstractText": "Floral morphology and labellum surface characters were measured.",
            "_calyx_retrieval_strategy": "exact_taxon_any",
            "_calyx_retrieval_query": "Dendrobium cuthbertsonii",
        },
    ]
    repository = FakeRepository()
    result = LiteratureEvidenceRoutingService(
        client=FakeClient(articles),
        repository=repository,
    ).route([target()], page_size=10, persist=False)

    assert result["persisted"] is False
    assert result["live_tig_eligible"] is False
    assert result["review_required"] is True
    assert result["diagnostics"]["publications"] == 2
    assert result["diagnostics"]["phylogenetic_sequence_context"] == 1
    assert result["diagnostics"]["trait_morphology_evidence"] == 1
    assert repository.rows == []


def test_service_preserves_secondary_phylogenetic_route_in_provenance():
    article = {
        "pmid": "36706796",
        "pmcid": "PMC9455781",
        "title": "Micromorphology of Labellum in Selected Dendrobium spp.",
        "abstractText": (
            "Labellum micromorphology was studied across species while ITS sequence data "
            "provided phylogenetic context."
        ),
        "isOpenAccess": "Y",
        "_calyx_retrieval_strategy": "exact_taxon_any",
        "_calyx_retrieval_query": '"Dendrobium cuthbertsonii"',
    }
    result = LiteratureEvidenceRoutingService(
        client=FakeClient([article]),
        repository=FakeRepository(),
    ).route([target()], persist=False)

    row = result["routes"][0]
    assert row["route"] == "trait_morphology_evidence"
    assert "phylogenetic_sequence_context" in row["provenance"]["secondary_routes"]
    assert row["provenance"]["primary_route_title_aware"] is True


def test_routing_service_persistence_is_idempotent_by_stable_route_id():
    article = {
        "pmid": "3",
        "title": "Reference genome and transcriptome of an orchid",
        "abstractText": "A reference genome and transcriptome resource is presented.",
    }
    repository = FakeRepository()
    service = LiteratureEvidenceRoutingService(
        client=FakeClient([article]),
        repository=repository,
    )
    first = service.route([target()], persist=True)
    second = service.route([target()], persist=True)

    assert first["routes"][0]["route"] == "genomic_resource"
    assert first["routes"][0]["route_id"] == second["routes"][0]["route_id"]
    assert len(repository.rows) == 2


def test_service_detects_strict_abstract_candidate_but_keeps_route_review_only():
    article = {
        "pmid": "4",
        "title": "Flower color regulation in Dendrobium cuthbertsonii",
        "abstractText": (
            "Expression of MYB1 was associated with flower color intensity in "
            "Dendrobium cuthbertsonii."
        ),
    }
    client = FakeClient(
        [article],
        annotations_by_id={"MED:4": [annotation()]},
    )
    result = LiteratureEvidenceRoutingService(
        client=client,
        repository=FakeRepository(),
    ).route([target()], persist=False)

    assert result["diagnostics"]["molecular_association_candidate"] == 1
    assert result["routes"][0]["route"] == "molecular_association_candidate"
    assert result["routes"][0]["provenance"]["strict_molecular_candidate_count"] == 1
    assert result["live_tig_eligible"] is False
