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


def test_exact_live_greeting_is_casual():
    assert speak_routes._is_casual(
        "Hello Calyx. What are you able to help me with?"
    ) is True


def test_scientific_question_after_greeting_is_not_casual():
    assert speak_routes._is_casual(
        "Hello Calyx. What does the literature say about orchid foliar uptake?"
    ) is False


def test_exact_live_greeting_does_not_call_retrieval_or_brain(monkeypatch):
    auth = {"subject": "owner-a"}
    conversation_id = speak_routes.create_conversation(
        speak_routes.ConversationCreateRequest(project_id="live-acceptance"), auth
    )["conversation_id"]

    def forbidden(*args, **kwargs):
        raise AssertionError("casual capability greeting must not invoke retrieval")

    def forbidden_mission(**kwargs):
        raise AssertionError("casual capability greeting must not invoke a Brain mission")

    monkeypatch.setattr(speak_routes, "_retrieval", forbidden)
    monkeypatch.setattr(
        speak_routes,
        "BRAIN_MISSION_SERVICE",
        SimpleNamespace(start=forbidden_mission),
    )

    result = speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(
            message="Hello Calyx. What are you able to help me with?",
            research_mode="auto",
        ),
        auth,
    )

    assert result["research"]["casual"] is True
    assert result["research"]["mission"] is None
    assert result["research"]["retrieval"]["status"] == "not_requested"
    assert result["answer"].startswith("Hello")
