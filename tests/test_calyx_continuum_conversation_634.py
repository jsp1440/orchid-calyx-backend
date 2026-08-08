from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import calyx_operator_chat as api
from app.security import verify_owner_or_api_key
from runtime.continuum_conversation import ContinuumConversationService


class FakeRetrieval:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def search(self, query):
        self.queries.append(query)
        return {
            "retrieval_mode": query.mode,
            "ranking_configuration_version": "test-rank-v1",
            "total_candidates": len(self.results),
            "total_eligible_results": len(self.results),
            "elapsed_ms": 1.25,
            "results": self.results,
        }


def evidence_result(*, excerpt: str | None = "Observed pollinator contact with the pollinarium."):
    return {
        "result_id": "result-1",
        "rank": 1,
        "fused_score": 0.91,
        "object_type": "CLAIM",
        "title": "Pollination study",
        "authorized_excerpt": excerpt,
        "citation": {
            "document_title": "Pollination study",
            "authors": ["Researcher A"],
            "revision_id": "rev-1",
            "locator": "p. 4",
        },
        "reliability_signals": {
            "peer_reviewed": "YES",
            "ai_generated": "NO",
            "citations_verified": "YES",
            "evidence_type": "PRIMARY",
        },
        "review_state": "REVIEWED",
        "verification_state": "VERIFIED",
        "temporal_status": "CURRENT",
        "display_policy": "LIMITED_PREVIEW_ONLY",
        "collections": ["literature"],
    }


def test_grounded_answer_preserves_evidence_and_non_authority():
    retrieval = FakeRetrieval([evidence_result()])
    service = ContinuumConversationService(retrieval)
    result = service.ask(
        "What do we know about this orchid's pollination?",
        context={"active_taxon_id": "taxon:fixture"},
    )

    assert result["epistemic_status"] == "continuum_evidence"
    assert result["evidence_count"] == 1
    assert result["evidence"][0]["citation"]["locator"] == "p. 4"
    assert "Pollination study" in result["answer"]
    assert result["model_knowledge_used"] is False
    assert result["scientific_interpretation_generated"] is False
    assert result["scientific_publication_authorized"] is False
    assert result["knowledge_graph_mutation_authorized"] is False
    assert result["answering_policy"] == "ASK_THE_CONTINUUM_FIRST"
    assert retrieval.queries[0].mode == "HYBRID"
    assert retrieval.queries[0].internal_access is True


def test_no_evidence_fails_closed_without_model_fallback():
    service = ContinuumConversationService(FakeRetrieval([]))
    result = service.ask("What evidence exists for an unsupported fixture question?")

    assert result["epistemic_status"] == "unknown"
    assert result["evidence_count"] == 0
    assert "not substituting general model knowledge" in result["answer"]
    assert result["model_knowledge_used"] is False


def test_metadata_only_evidence_does_not_leak_excerpt():
    service = ContinuumConversationService(FakeRetrieval([evidence_result(excerpt=None)]))
    result = service.ask("Show me the evidence metadata.")

    assert result["epistemic_status"] == "continuum_evidence_metadata_only"
    assert result["usable_excerpt_count"] == 0
    assert result["evidence"][0]["authorized_excerpt"] is None


def test_protected_ask_endpoint_records_both_sides_of_transcript(monkeypatch):
    api.reset_chat_for_tests()
    monkeypatch.setattr(
        api,
        "_continuum",
        ContinuumConversationService(FakeRetrieval([evidence_result()])),
    )
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "owner-fixture",
        "auth_type": "test",
    }
    client = TestClient(app)

    response = client.post(
        "/brain/mission-control/chat/ask",
        json={
            "question": "What does the Continuum know about pollination?",
            "context": {"active_project_id": "project-1"},
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["owner"] == "owner-fixture"
    assert payload["operator_message_id"].startswith("chat-")
    assert payload["calyx_message_id"].startswith("chat-")
    assert payload["requires_approval"] is False

    transcript = client.get("/brain/mission-control/chat/transcript").json()["messages"]
    assert [message.get("role", "calyx") for message in transcript] == ["operator", "calyx"]
    assert transcript[1]["requires_approval"] is False


def test_ask_endpoint_rejects_missing_owner_scope(monkeypatch):
    api.reset_chat_for_tests()
    monkeypatch.setattr(api, "_continuum", ContinuumConversationService(FakeRetrieval([])))
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": ""}
    response = TestClient(app).post(
        "/brain/mission-control/chat/ask",
        json={"question": "What do we know?"},
    )
    assert response.status_code == 403
