from datetime import datetime, timezone

from app.literature_extraction.models import (
    AnalysisManifest,
    Claim,
    Entity,
    Evidence,
    Measurement,
    NormalizedEvidenceRecord,
    PaperKnowledge,
    PaperMetadata,
    Provenance,
    PublicationDecision,
    SourceDocument,
    SourceSpan,
)
from runtime.knowledge_graph.publication_eligible_paper_graph import (
    build_publication_eligible_paper_graph_specs,
)
from runtime.knowledge_graph.publisher import canonical_key
from runtime.knowledge_graph.vocabulary import domain_for_edge_type


def _prov(review_status: str, method: str = "human_annotated") -> Provenance:
    return Provenance(
        method=method,
        confidence=0.95,
        review_status=review_status,
    )


def _paper() -> PaperKnowledge:
    accepted_claim = Claim(
        claim_id="accepted-result",
        statement="Laelia anceps foliar treatment increased tissue nitrogen.",
        claim_type="result",
        subject_ids=["taxon-1"],
        evidence_ids=["e1"],
        provenance=_prov("unreviewed", method="model_extracted"),
    )
    reviewed_but_not_publishable = Claim(
        claim_id="reviewed-hypothesis",
        statement="Direct foliar uptake explains the result.",
        claim_type="hypothesis",
        subject_ids=["taxon-1"],
        evidence_ids=["e1"],
        provenance=_prov("accepted"),
    )
    record = NormalizedEvidenceRecord(
        record_id="record-1",
        source_claim_id=accepted_claim.claim_id,
        evidence_ids=["e1"],
        statement=accepted_claim.statement,
        normalized_statement=accepted_claim.statement,
        domain="trait",
        polarity="positive",
        canonical_entity_ids=["taxon-1"],
        extraction_confidence=0.95,
        normalization_confidence=0.95,
        review_status="accepted",
        source_excerpts=["Tissue nitrogen increased."],
        provenance=_prov("accepted"),
    )
    return PaperKnowledge(
        paper_id="paper-eligible-1",
        source=SourceDocument(
            content_hash="0123456789abcdef",
            media_type="application/pdf",
            original_filename="paper.pdf",
        ),
        metadata=PaperMetadata(title="Reviewed orchid physiology study"),
        entities=[
            Entity(
                entity_id="taxon-1",
                entity_type="taxon",
                name="Laelia anceps",
                normalized_name="Laelia anceps",
                provenance=_prov("accepted"),
            )
        ],
        claims=[accepted_claim, reviewed_but_not_publishable],
        measurements=[
            Measurement(
                measurement_id="m1",
                subject_id="taxon-1",
                property="tissue nitrogen",
                value=2.5,
                value_text="2.5",
                unit="percent",
                evidence_ids=["e1"],
                provenance=_prov("corrected"),
            )
        ],
        evidence=[
            Evidence(
                evidence_id="e1",
                excerpt="Tissue nitrogen increased.",
                span=SourceSpan(page_start=4, page_end=4),
                evidence_type="text",
                supports_ids=[accepted_claim.claim_id],
            )
        ],
        normalized_evidence_records=[record],
        publication_decisions=[
            PublicationDecision(
                publication_decision_id="publication-1",
                review_item_id="review-1",
                source_record_id=record.record_id,
                status="eligible_for_publication",
                reason_codes=["human_reviewed"],
            )
        ],
        analysis_manifest=AnalysisManifest(
            analysis_id="analysis-1",
            analysis_version=1,
            created_at=datetime.now(timezone.utc),
            pipeline_version="test",
            status="completed",
        ),
    )


def test_publication_decision_is_authoritative_for_claim_inclusion():
    bundle = build_publication_eligible_paper_graph_specs(
        _paper(),
        taxon_keys_by_entity_id={"taxon-1": canonical_key("taxon", 42)},
    )
    result_key = canonical_key("result", "paper-eligible-1:accepted-result")
    nodes = {node.key(): node for node in bundle.nodes}
    assert result_key in nodes
    assert canonical_key("hypothesis", "paper-eligible-1:reviewed-hypothesis") not in nodes
    assert nodes[result_key].confidence_label == "publication_eligible"
    assert nodes[result_key].payload["publication_eligible"] is True
    assert nodes[result_key].payload["publication_eligible_record_ids"] == ["record-1"]
    assert bundle.candidate_objects_omitted == 1


def test_eligible_claim_and_reviewed_measurement_connect_to_taxon():
    taxon_key = canonical_key("taxon", 42)
    bundle = build_publication_eligible_paper_graph_specs(
        _paper(),
        taxon_keys_by_entity_id={"taxon-1": taxon_key},
    )
    about_edges = [edge for edge in bundle.edges if edge.edge_type == "about_taxon"]
    measurement_edges = [
        edge for edge in bundle.edges if edge.edge_type == "measurement_of"
    ]
    assert len(about_edges) == 1
    assert about_edges[0].to_key == taxon_key
    assert about_edges[0].payload["publication_eligible"] is True
    assert about_edges[0].payload["publication_eligible_record_ids"] == ["record-1"]
    assert len(measurement_edges) == 1
    assert measurement_edges[0].to_key == taxon_key
    assert domain_for_edge_type("about_taxon") == "scientific_method"


def test_no_publication_decisions_fail_closed_for_claim_nodes():
    paper = _paper()
    paper.publication_decisions = []
    bundle = build_publication_eligible_paper_graph_specs(
        paper,
        taxon_keys_by_entity_id={"taxon-1": canonical_key("taxon", 42)},
    )
    keys = {node.key() for node in bundle.nodes}
    assert canonical_key("result", "paper-eligible-1:accepted-result") not in keys
    assert canonical_key("hypothesis", "paper-eligible-1:reviewed-hypothesis") not in keys
    assert not any(edge.edge_type == "about_taxon" for edge in bundle.edges)


def test_unreviewed_taxon_entity_cannot_create_free_standing_document_edge():
    paper = _paper()
    paper.entities[0].provenance = _prov("unreviewed", method="model_extracted")
    paper.publication_decisions = []
    bundle = build_publication_eligible_paper_graph_specs(
        paper,
        taxon_keys_by_entity_id={"taxon-1": canonical_key("taxon", 42)},
    )
    assert not any(edge.edge_type == "documented_by" for edge in bundle.edges)
