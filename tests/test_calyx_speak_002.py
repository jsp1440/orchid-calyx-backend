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
    monkeypatch.setattr(
        speak_routes,
        "_retrieval",
        lambda message, mode, limit, internal_access: {
            "results": [],
            "total_eligible_results": 0,
            "retrieval_mode": mode,
        },
    )
    return store


def auth(subject: str) -> dict[str, str]:
    return {"subject": subject}


def create_for(subject: str, project_id: str = "vision") -> str:
    result = speak_routes.create_conversation(
        speak_routes.ConversationCreateRequest(
            title="Vision discussion",
            project_id=project_id,
        ),
        auth(subject),
    )
    return result["conversation_id"]


def test_conversations_are_owner_scoped(isolated_store):
    conversation_id = create_for("owner-a")
    assert speak_routes.get_conversation(conversation_id, auth("owner-a"))["owner"] == "owner-a"

    with pytest.raises(Exception) as exc_info:
        speak_routes.get_conversation(conversation_id, auth("owner-b"))
    assert getattr(exc_info.value, "status_code", None) == 404
    assert speak_routes.list_conversations(auth("owner-b"))["conversations"] == []


def test_casual_turn_does_not_launch_brain_mission(monkeypatch):
    conversation_id = create_for("owner-a")

    def forbidden_start(**kwargs):
        raise AssertionError("casual conversation must not launch a Brain mission")

    monkeypatch.setattr(speak_routes, "BRAIN_MISSION_SERVICE", SimpleNamespace(start=forbidden_start))
    result = speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(message="Hello Calyx"),
        auth("owner-a"),
    )

    assert result["research"]["casual"] is True
    assert result["research"]["mission"] is None
    assert "Hello" in result["answer"]
    assert result["provider"]["name"] == "deterministic-governed"


def test_scientific_turn_launches_governed_mission_and_records_provenance(monkeypatch):
    conversation_id = create_for("owner-a", "calyx-vision")
    calls = []

    def start(**kwargs):
        calls.append(kwargs)
        return {
            "mission_id": "mission-vision-1",
            "state": "AWAITING_HUMAN_REVIEW",
            "conclusions": [{"type": "inference", "text": "Glossary images should preserve machine-readable visual structure."}],
            "missing_evidence": ["controlled orchid-specific vision benchmark"],
            "confidence": 0.74,
            "review_status": "HUMAN_REVIEW_REQUIRED",
            "publication_eligibility": {
                "eligible": False,
                "automatic_publication": False,
                "blockers": ["HUMAN_REVIEW_REQUIRED"],
            },
        }

    monkeypatch.setattr(speak_routes, "BRAIN_MISSION_SERVICE", SimpleNamespace(start=start))
    result = speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(
            message="What visual information should Calyx Vision require from glossary illustrations?",
            research_mode="auto",
        ),
        auth("owner-a"),
    )

    assert len(calls) == 1
    assert calls[0]["tenant_id"] == "owner-a"
    assert calls[0]["project_id"] == "calyx-vision"
    assert result["research"]["mission"]["mission_id"] == "mission-vision-1"
    assert "machine-readable visual structure" in result["answer"]
    metadata = result["calyx_message"]["metadata"]
    assert metadata["mission_id"] == "mission-vision-1"
    assert metadata["request_hash"]
    assert metadata["publication_boundary"].startswith("human-review")


def test_followup_mission_receives_prior_thread_context(monkeypatch):
    conversation_id = create_for("owner-a", "calyx-vision")
    mission_questions = []

    def start(**kwargs):
        mission_questions.append(kwargs["question"])
        return {
            "mission_id": f"mission-{len(mission_questions)}",
            "state": "AWAITING_HUMAN_REVIEW",
            "conclusions": [{"text": "Provisional governed response."}],
            "missing_evidence": [],
            "confidence": 0.6,
            "review_status": "HUMAN_REVIEW_REQUIRED",
            "publication_eligibility": {"eligible": False, "automatic_publication": False, "blockers": []},
        }

    monkeypatch.setattr(speak_routes, "BRAIN_MISSION_SERVICE", SimpleNamespace(start=start))
    first = "What structures should the glossary illustrations encode for Calyx Vision?"
    second = "Which of those are essential rather than merely useful?"

    speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(message=first),
        auth("owner-a"),
    )
    speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(message=second),
        auth("owner-a"),
    )

    assert len(mission_questions) == 2
    assert first in mission_questions[1]
    assert second in mission_questions[1]
    conversation = speak_routes.get_conversation(conversation_id, auth("owner-a"))
    roles = [message["role"] for message in conversation["messages"]]
    assert roles.count("operator") == 2
    assert roles.count("calyx") == 2
    assert roles.count("tool") == 2
