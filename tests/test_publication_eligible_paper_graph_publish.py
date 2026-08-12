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
from runtime.knowledge_graph.models import Node
from runtime.knowledge_graph.publication_eligible_paper_graph import (
    build_publication_eligible_paper_graph_specs,
)
from runtime.knowledge_graph.publisher import DomainAdapter, canonical_key, publish_domain
from runtime.knowledge_graph.repository import InMemoryGraphRepository


def _prov(review_status: str, method: str = "human_annotated") -> Provenance:
    return Provenance(method=method, confidence=0.95, review_status=review_status)


def _paper() -> PaperKnowledge:
    claim = Claim(
        claim_id="result-1",
        statement="Laelia anceps tissue nitrogen increased after treatment.",
        claim_type="result",
        subject_ids=["taxon-1"],
        evidence_ids=["e1"],
        provenance=_prov("unreviewed", method="model_extracted"),
    )
    record = NormalizedEvidenceRecord(
        record_id="record-1",
        source_claim_id=claim.claim_id,
        evidence_ids=["e1"],
        statement=claim.statement,
        normalized_statement=claim.statement,
        domain="trait",
        polarity="positive",
        canonical_entity_ids=["taxon-1"],
        extraction_confidence=0.95,
        normalization_confidence=0.95,
        review_status="accepted",
        provenance=_prov("accepted"),
    )
    return PaperKnowledge(
        paper_id="publisher-paper",
        source=SourceDocument(
            content_hash="0123456789abcdef",
            media_type="application/pdf",
            original_filename="paper.pdf",
        ),
        metadata=PaperMetadata(title="Publisher integration study"),
        entities=[
            Entity(
                entity_id="taxon-1",
                entity_type="taxon",
                name="Laelia anceps",
                normalized_name="Laelia anceps",
                provenance=_prov("accepted"),
            )
        ],
        claims=[claim],
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
                excerpt="Tissue nitrogen increased to 2.5 percent.",
                span=SourceSpan(page_start=3, page_end=3),
                evidence_type="text",
                supports_ids=[claim.claim_id],
            )
        ],
        normalized_evidence_records=[record],
        publication_decisions=[
            PublicationDecision(
                publication_decision_id="pub-1",
                review_item_id="review-1",
                source_record_id=record.record_id,
                status="eligible_for_publication",
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


def test_publication_eligible_bundle_uses_only_registered_graph_semantics():
    taxon_key = canonical_key("taxon", 42)
    taxon = Node(
        kg_node_id=1,
        node_type="taxon",
        canonical_key=taxon_key,
        display_label="Laelia anceps",
        source_table="taxonomy",
        source_pk="42",
    )
    repo = InMemoryGraphRepository(nodes=[taxon])
    bundle = build_publication_eligible_paper_graph_specs(
        _paper(),
        taxon_keys_by_entity_id={"taxon-1": taxon_key},
    )
    adapter = DomainAdapter(
        domain="scientific_method",
        source_table="literature_extraction.paper_knowledge",
        produce=lambda rows: (list(bundle.nodes), list(bundle.edges)),
    )

    result = publish_domain(repo, adapter, [{}])

    assert result.invalid == []
    assert result.nodes_written == len(bundle.nodes)
    assert result.edges_written == len(bundle.edges)
    edge_types = {edge.edge_type for edge in repo.all_edges()}
    assert "about_taxon" in edge_types
    assert "measurement_of" in edge_types
    assert "reports_result" in edge_types
    assert "supported_by_evidence" in edge_types
