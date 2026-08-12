from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.calyx_conversation import speak_routes
from app.calyx_conversation.provider import DeterministicGovernedReplyProvider
from app.calyx_conversation.store import ConversationStore
from app.calyx_conversation.workspace_outputs import grounded_workspace_outputs


@pytest.fixture(autouse=True)
def isolated_store(monkeypatch):
    store = ConversationStore(dsn="")
    monkeypatch.setattr(speak_routes, "STORE", store)
    monkeypatch.setattr(
        speak_routes,
        "configured_reply_provider",
        lambda: DeterministicGovernedReplyProvider(),
    )
    return store


def auth():
    return {"subject": "owner-output"}


def _retrieval_result(*, result_id: str, title: str, score: float) -> dict:
    return {
        "result_id": result_id,
        "rank": 1,
        "title": title,
        "object_type": "LITERATURE",
        "review_state": "REVIEWED",
        "verification_state": "VERIFIED",
        "fused_score": score,
        "citation": {
            "document_id": "doc-velamen-1",
            "revision_id": "rev-2026-08",
            "identifier": "doi:10.example/velamen",
            "locator": {"page": 12},
        },
    }


def test_grounded_outputs_preserve_retrieval_provenance_and_candidate_boundary():
    retrieval = {
        "total_eligible_results": 1,
        "ranking_configuration_version": "rank-v1",
        "results": [_retrieval_result(result_id="result-velamen-1", title="Velamen anatomy study", score=0.82)],
    }
    mission = {
        "mission_id": "mission-1",
        "supporting_evidence": [{"candidate_id": "cand-1", "subject": "velamen", "predicate": "is associated with", "value": "orchid root water relations"}],
        "contradicting_evidence": [],
        "missing_evidence": ["comparative replicated measurements across growth forms"],
    }
    outputs = grounded_workspace_outputs(retrieval=retrieval, mission=mission)
    assert [item["kind"] for item in outputs] == ["table", "table", "text"]
    retrieval_output = outputs[0]
    assert retrieval_output["provenance"]["source_module"] == "evidence-retrieval"
    assert retrieval_output["provenance"]["evidence_status"] == "unknown"
    assert retrieval_output["provenance"]["source_id"].startswith("retrieval-set-")
    row = retrieval_output["payload"]["rows"][0]
    assert row["source_id"] == "result-velamen-1"
    assert row["document_id"] == "doc-velamen-1"
    assert row["revision_id"] == "rev-2026-08"
    assert row["citation"]["locator"] == {"page": 12}
    assert outputs[1]["provenance"]["generated"] is True
    assert outputs[1]["provenance"]["evidence_status"] == "derived"
    assert outputs[2]["provenance"]["evidence_status"] == "derived"


def test_empty_or_casual_tool_state_creates_no_fake_outputs():
    assert grounded_workspace_outputs(retrieval={"results": [], "total_eligible_results": 0}, mission=None) == []


def test_speak_turn_returns_server_grounded_workspace_outputs(monkeypatch):
    def retrieval(*args, **kwargs):
        return {"total_eligible_results": 1, "retrieval_mode": "HYBRID", "ranking_configuration_version": "rank-v1", "results": [_retrieval_result(result_id="result-output-1", title="Velamen root anatomy", score=0.91)]}

    def mission_start(**kwargs):
        return {"mission_id": "mission-output-1", "state": "AWAITING_HUMAN_REVIEW", "supporting_evidence": [{"candidate_id": "candidate-output-1", "subject": "velamen", "predicate": "has functional relevance to", "value": "orchid root water relations"}], "contradicting_evidence": [], "missing_evidence": ["orchid-wide comparative benchmark"], "conclusions": [{"text": "Provisional grounded conclusion."}], "confidence": 0.7, "review_status": "HUMAN_REVIEW_REQUIRED", "publication_eligibility": {"eligible": False, "automatic_publication": False, "blockers": ["HUMAN_REVIEW_REQUIRED"]}}

    monkeypatch.setattr(speak_routes, "_retrieval", retrieval)
    monkeypatch.setattr(speak_routes, "BRAIN_MISSION_SERVICE", SimpleNamespace(start=mission_start))
    conversation_id = speak_routes.create_conversation(speak_routes.ConversationCreateRequest(project_id="lexicon"), auth())["conversation_id"]
    result = speak_routes.append_turn(conversation_id, speak_routes.ConversationTurnRequest(message="Why is velamen important in orchid roots?", research_mode="always"), auth())
    outputs = result["workspace_outputs"]
    assert len(outputs) == 3
    assert outputs[0]["payload"]["rows"][0]["source_id"] == "result-output-1"
    assert outputs[1]["provenance"]["evidence_status"] == "derived"
    assert result["epistemic_policy"]["workspace_outputs_are_automatically_evidence"] is False
    assert result["calyx_message"]["metadata"]["workspace_output_ids"] == [item["id"] for item in outputs]


def test_status_exposes_server_grounded_output_contract():
    status = speak_routes.speak_status(auth())
    assert status["release"] == "CALYX-SPEAK-005-WORKSPACE-OUTPUTS"
    assert status["workspace_outputs"]["supported"] is True
    assert status["workspace_outputs"]["server_grounded_only"] is True
    assert status["automatic_publication"] is False
    assert status["knowledge_graph_mutation"] is False
