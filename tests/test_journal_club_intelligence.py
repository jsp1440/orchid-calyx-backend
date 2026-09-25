import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.intake.journal_club import (
    JOURNAL_CLUB_PARSER_VERSION,
    JournalClubIntakeRequest,
    canonical_journal_club_text,
    journal_club_summary,
    parse_journal_club_transcript,
)
from app.security import verify_owner_or_api_key

TRANSCRIPT = """
This episode compares query-adaptive hybrid search with Graph RAG for dataset discovery.
The authors report a benchmark and ablation study, then discuss agent orchestration,
context engineering, and a reranker for higher precision.
"""


def test_journal_club_parser_maps_supported_techniques_with_exact_spans():
    items = parse_journal_club_transcript(
        title="Query-Adaptive Hybrid Search",
        transcript=TRANSCRIPT,
        source_url="https://journalclub.io/example",
        episode_id="jc-001",
    )

    techniques = {item["technology_scout"]["technique"] for item in items}
    assert {
        "GRAPH_RAG",
        "HYBRID_RETRIEVAL",
        "QUERY_ADAPTIVE_RETRIEVAL",
        "AGENT_ORCHESTRATION",
        "CONTEXT_ENGINEERING",
        "RERANKING",
        "EVALUATION",
    } <= techniques

    for item in items:
        assert item["domain"] == "technology"
        assert item["lifecycle"] == "DISCOVERED"
        assert item["knowledge_delta"] == "UNASSESSED"
        assert item["verification_required"] is True
        assert item["canonical_graph_mutated"] is False
        assert item["publication_performed"] is False
        assert "production_implementation" in item["approval_required_for"]
        for span in item["technology_scout"]["evidence_spans"]:
            assert TRANSCRIPT[span["start"] : span["end"]] == span["exact_text"]



def test_one_paper_can_emit_multiple_distinct_technique_candidates():
    items = parse_journal_club_transcript(
        title="Graph RAG and hybrid retrieval",
        transcript="Graph RAG is compared with hybrid retrieval in one paper.",
        doi="10.1234/shared-paper",
        episode_id="jc-shared",
    )
    fingerprints = [item["knowledge_fingerprint"] for item in items]
    assert len(fingerprints) >= 2
    assert len(fingerprints) == len(set(fingerprints))
    assert all(item["dois"] == ["10.1234/shared-paper"] for item in items)


def test_irrelevant_transcript_fails_closed_without_guessing():
    items = parse_journal_club_transcript(
        title="A botanical discussion",
        transcript="The speakers compare flower color and fragrance in cultivated orchids.",
        episode_id="jc-irrelevant",
    )
    assert items == []
    summary = journal_club_summary(items)
    assert summary["items_discovered"] == 0
    assert summary["provider_calls"] == 0
    assert summary["automatic_implementation_performed"] is False


def test_canonical_source_is_stable_and_provenance_bearing():
    first = canonical_journal_club_text(
        title="Graph RAG",
        transcript="Graph RAG benchmark.",
        source_url="https://journalclub.io/example",
        episode_id="jc-002",
        doi="10.1234/example",
    )
    second = canonical_journal_club_text(
        title="Graph RAG",
        transcript="Graph RAG benchmark.",
        source_url="https://journalclub.io/example",
        episode_id="jc-002",
        doi="10.1234/example",
    )
    assert first == second
    assert "Source-System: JournalClub.io" in first
    assert "Episode-ID: jc-002" in first
    assert "DOI: 10.1234/example" in first


def test_authenticated_route_uses_existing_source_and_intelligence_ledgers(monkeypatch):
    from app.intake import routes

    captured = {}

    def fake_create_source(**kwargs):
        captured["source"] = kwargs
        return {"id": 91, "status": "PARSED"}

    def fake_record_intelligence_items(**kwargs):
        captured["items"] = kwargs
        return [{"id": 501, "new_observation": True}]

    monkeypatch.setattr(routes, "create_source", fake_create_source)
    monkeypatch.setattr(routes, "record_intelligence_items", fake_record_intelligence_items)

    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test"}
    client = TestClient(app)

    response = client.post(
        "/api/intake/journal-club",
        json={
            "title": "Graph RAG for explainable discovery",
            "transcript": TRANSCRIPT,
            "source_url": "https://journalclub.io/example",
            "episode_id": "jc-003",
            "imported_by": "test",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["journal_club"]["parser_version"] == JOURNAL_CLUB_PARSER_VERSION
    assert payload["journal_club"]["items_discovered"] >= 7
    assert payload["journal_club"]["provider_calls"] == 0
    assert payload["publication_performed"] is False
    assert payload["canonical_graph_mutated"] is False
    assert payload["automatic_implementation_performed"] is False

    assert captured["source"]["source_type"] == "text"
    assert captured["source"]["source_url"] == "https://journalclub.io/example"
    assert captured["items"]["source_id"] == 91
    assert captured["items"]["sender"] == "journalclub.io"
    assert all(
        item["technology_scout"]["review_state"] == "CANDIDATE"
        for item in captured["items"]["items"]
    )


def test_request_rejects_missing_transcript():
    with pytest.raises(ValidationError):
        JournalClubIntakeRequest(title="x", transcript="")
