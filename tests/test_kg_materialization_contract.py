from __future__ import annotations

import json

import pytest

from app.calyx_orchestrator.kg_materialization import (
    EvidenceState,
    KGMaterializationRecord,
    KGReadThroughGateway,
    KnowledgeGraphPipeline,
)


def _record(record_id: str, source_class: str) -> KGMaterializationRecord:
    return KGMaterializationRecord(
        record_id=record_id,
        source_domain="literature",
        source_class=source_class,
        evidence_state=EvidenceState.REVIEW_REQUIRED,
        taxon_id="taxon:1",
        taxon_name="Laelia anceps",
        predicate="has_trait",
        value="epiphytic",
        provenance_chain=(
            {
                "source": "example-paper",
                "doi": "10.0000/example",
                "latitude": 34.0,
                "longitude": -120.0,
                "api_key": "never-serialize-me",
            },
        ),
    )


def test_pipeline_forbids_publication_and_mutation_authority() -> None:
    for kwargs in (
        {"automatic_publication": True},
        {"knowledge_graph_mutation": True},
        {"taxonomy_activation": True},
        {"scientific_publication": True},
    ):
        with pytest.raises(ValueError, match="cannot grant publication or mutation authority"):
            KnowledgeGraphPipeline(**kwargs)


def test_source_precedence_and_safe_json_serialization() -> None:
    pipeline = KnowledgeGraphPipeline()
    records = [
        _record("external", "external_discovery"),
        _record("reviewed", "canonical_reviewed"),
        _record("unreviewed", "canonical_unreviewed"),
    ]

    payload = pipeline.serialize(records)
    assert [item["record_id"] for item in payload["records"]] == [
        "reviewed",
        "unreviewed",
        "external",
    ]
    assert payload["automatic_publication"] is False
    assert payload["knowledge_graph_mutation"] is False
    assert payload["taxonomy_activation"] is False
    assert payload["scientific_publication"] is False

    encoded = json.dumps(payload).casefold()
    assert '"latitude"' not in encoded
    assert '"longitude"' not in encoded
    assert '"api_key"' not in encoded
    assert "10.0000/example" in encoded


def test_unavailable_read_through_is_unknown_not_fabricated_zero() -> None:
    result = KGReadThroughGateway(available=False).query(
        taxon_id="taxon:1", predicate="pollinated_by"
    )
    assert result["state"] == "UNKNOWN"
    assert result["records"] is None
    assert result["edge_presence"] is None
    assert result["reason"] == "knowledge_graph_unavailable"


def test_available_gateway_still_returns_unknown_when_no_reviewable_record_exists() -> None:
    result = KGReadThroughGateway(available=True, records=[]).query(
        taxon_id="taxon:missing", predicate="has_trait"
    )
    assert result["state"] == "UNKNOWN"
    assert result["records"] == []
    assert result["edge_presence"] is None
    assert result["reason"] == "no_reviewable_records_found"


def test_materialization_record_cannot_disable_human_review_gate() -> None:
    with pytest.raises(ValueError, match="human-review gated"):
        KGMaterializationRecord(
            record_id="unsafe",
            source_domain="traits",
            source_class="canonical_reviewed",
            evidence_state=EvidenceState.VERIFIED,
            taxon_id="taxon:1",
            taxon_name="Laelia anceps",
            predicate="has_trait",
            value="epiphytic",
            human_review_required=False,
        )
