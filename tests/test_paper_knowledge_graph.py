from datetime import datetime, timezone

from app.literature_extraction.models import (
    AnalysisManifest,
    Claim,
    Evidence,
    Measurement,
    PaperKnowledge,
    PaperMetadata,
    Provenance,
    Reference,
    SourceDocument,
    SourceSpan,
)
from runtime.knowledge_graph.paper_knowledge_graph import build_paper_graph_specs
from runtime.knowledge_graph.publisher import canonical_key


def _prov(review_status: str) -> Provenance:
    return Provenance(
        method="human_annotated" if review_status != "unreviewed" else "model_extracted",
        confidence=0.9,
        review_status=review_status,
    )


def _paper() -> PaperKnowledge:
    return PaperKnowledge(
        paper_id="paper-1",
        source=SourceDocument(
            content_hash="0123456789abcdef",
            media_type="application/pdf",
            original_filename="paper.pdf",
        ),
        metadata=PaperMetadata(title="Orchid physiology experiment"),
        claims=[
            Claim(
                claim_id="accepted-result",
                statement="Foliar treatment increased tissue nitrogen.",
                claim_type="result",
                evidence_ids=["e1"],
                provenance=_prov("accepted"),
            ),
            Claim(
                claim_id="candidate-hypothesis",
                statement="Leaves may absorb nitrogen directly.",
                claim_type="hypothesis",
                provenance=_prov("unreviewed"),
            ),
        ],
        measurements=[
            Measurement(
                measurement_id="m1",
                subject_id="taxon-entity-1",
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
                supports_ids=["accepted-result"],
            )
        ],
        references=[Reference(reference_id="r1", raw_citation="Example 2020")],
        analysis_manifest=AnalysisManifest(
            analysis_id="analysis-1",
            analysis_version=1,
            created_at=datetime.now(timezone.utc),
            pipeline_version="test",
            status="completed",
        ),
    )


def test_paper_graph_fails_closed_for_unreviewed_claims_by_default():
    bundle = build_paper_graph_specs(_paper())
    keys = {node.key() for node in bundle.nodes}
    edge_types = {edge.edge_type for edge in bundle.edges}

    assert canonical_key("publication", "paper-1") in keys
    assert canonical_key("result", "paper-1:accepted-result") in keys
    assert canonical_key("hypothesis", "paper-1:candidate-hypothesis") not in keys
    assert canonical_key("measurement", "paper-1:m1") in keys
    assert canonical_key("evidence", "paper-1:e1") in keys
    assert canonical_key("reference", "paper-1:r1") in keys
    assert bundle.candidate_objects_omitted == 1
    assert "reports_result" in edge_types
    assert "has_measurement" in edge_types
    assert "supported_by_evidence" in edge_types
    assert "cites" in edge_types


def test_candidate_graph_representation_requires_explicit_opt_in():
    bundle = build_paper_graph_specs(_paper(), include_candidates=True)
    keys = {node.key() for node in bundle.nodes}
    assert canonical_key("hypothesis", "paper-1:candidate-hypothesis") in keys
    assert bundle.candidate_objects_omitted == 0


def test_taxon_edges_require_canonical_resolver_output():
    paper = _paper()
    # No extracted entity exists in this minimal fixture, so supplying no mapping
    # can never invent a taxonomy node or a documented_by edge.
    bundle = build_paper_graph_specs(paper)
    assert not any(edge.edge_type == "documented_by" for edge in bundle.edges)
