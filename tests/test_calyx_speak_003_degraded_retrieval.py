from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.calyx_conversation import speak_routes
from app.calyx_conversation.provider import DeterministicGovernedReplyProvider
from app.calyx_conversation.store import ConversationStore


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


def auth() -> dict[str, str]:
    return {"subject": "owner-a"}


def create_conversation() -> str:
    return speak_routes.create_conversation(
        speak_routes.ConversationCreateRequest(project_id="vision"),
        auth(),
    )["conversation_id"]


def test_casual_turn_never_requires_semantic_retrieval(monkeypatch):
    conversation_id = create_conversation()

    def unavailable(*args, **kwargs):
        raise RuntimeError("SEMANTIC_INDEX_UNAVAILABLE")

    monkeypatch.setattr(speak_routes, "_retrieval", unavailable)
    result = speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(
            message="Hello Calyx. What are you able to help me with?",
            research_mode="auto",
        ),
        auth(),
    )

    assert result["research"]["casual"] is True
    assert result["research"]["retrieval"]["status"] == "not_requested"
    assert result["workspace_outputs"] == []
    assert result["answer"].startswith("Hello")


def test_scientific_turn_survives_semantic_index_outage(monkeypatch):
    conversation_id = create_conversation()

    def unavailable(*args, **kwargs):
        raise RuntimeError("SEMANTIC_INDEX_UNAVAILABLE")

    def mission_start(**kwargs):
        raise RuntimeError("SEMANTIC_INDEX_UNAVAILABLE")

    monkeypatch.setattr(speak_routes, "_retrieval", unavailable)
    monkeypatch.setattr(
        speak_routes,
        "BRAIN_MISSION_SERVICE",
        SimpleNamespace(start=mission_start),
    )

    result = speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(
            message="What visual information should Calyx Vision require from glossary illustrations?",
            research_mode="always",
        ),
        auth(),
    )

    retrieval = result["research"]["retrieval"]
    assert retrieval["status"] == "unavailable"
    assert retrieval["error"] == "SEMANTIC_INDEX_UNAVAILABLE"
    assert result["research"]["mission"] is None
    assert result["research"]["mission_error"] == "SEMANTIC_INDEX_UNAVAILABLE"
    assert result["workspace_outputs"] == []
    assert "could not complete a governed Brain mission" in result["answer"]
    assert result["calyx_message"]["metadata"]["retrieval_status"] == "unavailable"


def test_speak_status_exposes_degraded_mode_contract():
    result = speak_routes.speak_status(auth())
    assert result["release"] == "CALYX-SPEAK-005-WORKSPACE-OUTPUTS"
    assert result["semantic_retrieval_degraded_mode"] is True
    assert result["interaction_context"]["supported"] is True
    assert result["interaction_context"]["evidence"] is False
    assert result["workspace_outputs"]["supported"] is True
    assert result["workspace_outputs"]["server_grounded_only"] is True
    assert result["automatic_publication"] is False
    assert result["knowledge_graph_mutation"] is False
