from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.calyx_conversation import speak_routes
from app.calyx_conversation.interaction_context import sanitize_interaction_context
from app.calyx_conversation.provider import GeneratedReply
from app.calyx_conversation.store import ConversationStore


@dataclass
class CapturingProvider:
    context: dict | None = None

    def generate(self, *, messages, governed_context):
        self.context = governed_context
        return GeneratedReply(
            text="I understand the current interface context.",
            provider="capture",
            model="capture-v1",
            request_hash="context-test",
        )


@pytest.fixture
def isolated(monkeypatch):
    store = ConversationStore(dsn="")
    provider = CapturingProvider()
    monkeypatch.setattr(speak_routes, "STORE", store)
    monkeypatch.setattr(speak_routes, "configured_reply_provider", lambda: provider)
    monkeypatch.setattr(
        speak_routes,
        "_retrieval",
        lambda message, mode, limit, internal_access: {
            "results": [],
            "total_eligible_results": 0,
            "retrieval_mode": mode,
        },
    )
    return store, provider


def auth():
    return {"subject": "owner-context"}


def test_sanitizer_forces_ui_context_to_non_evidence_and_bounds_trail():
    context = sanitize_interaction_context(
        {
            "surface": "illustrated-orchid-lexicon",
            "concept": "velamen",
            "context_is_evidence": True,
            "arbitrary_scientific_claim": "must not reach provider",
            "current_surface": {
                "surface": "lexicon-entry",
                "module": "illustrated-orchid-lexicon",
                "object_type": "lexicon_concept",
                "object_id": "velamen",
                "label": "Velamen",
                "metadata": {"claim": "untrusted nested content"},
            },
            "session_trail": [
                {"surface": "lexicon-entry", "module": "lexicon", "object_id": f"term-{index}"}
                for index in range(12)
            ],
        }
    )

    assert context["context_is_evidence"] is False
    assert context["concept"] == "velamen"
    assert "arbitrary_scientific_claim" not in context
    assert "metadata" not in context["current_surface"]
    assert len(context["session_trail"]) == 8
    assert context["session_trail"][0]["object_id"] == "term-4"


def test_turn_passes_sanitized_page_context_to_provider_and_persists_it(isolated):
    store, provider = isolated
    created = speak_routes.create_conversation(
        speak_routes.ConversationCreateRequest(
            title="Adaptive lexicon session",
            project_id="illustrated-orchid-lexicon",
        ),
        auth(),
    )
    conversation_id = created["conversation_id"]

    result = speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(
            message="Why is this important?",
            research_mode="never",
            context={
                "surface": "illustrated-orchid-lexicon",
                "concept": "velamen",
                "current_concept_label": "Velamen",
                "context_is_evidence": True,
                "current_surface": {
                    "surface": "lexicon-entry",
                    "module": "illustrated-orchid-lexicon",
                    "object_type": "lexicon_concept",
                    "object_id": "velamen",
                    "label": "Velamen",
                },
            },
        ),
        auth(),
    )

    interaction = provider.context["interaction_context"]
    assert interaction["concept"] == "velamen"
    assert interaction["current_surface"]["label"] == "Velamen"
    assert interaction["context_is_evidence"] is False
    assert provider.context["epistemic_policy"]["interaction_context_is_evidence"] is False
    assert result["interaction_context"] == interaction

    stored = store.get(conversation_id, owner="owner-context")
    operator = next(message for message in stored["messages"] if message["role"] == "operator")
    assert operator["metadata"]["context"] == interaction


def test_status_advertises_context_support_without_knowledge_mutation(isolated):
    status = speak_routes.speak_status(auth())
    assert status["release"] == "CALYX-SPEAK-005-WORKSPACE-OUTPUTS"
    assert status["interaction_context"]["supported"] is True
    assert status["interaction_context"]["evidence"] is False
    assert status["workspace_outputs"]["supported"] is True
    assert status["workspace_outputs"]["server_grounded_only"] is True
    assert status["automatic_publication"] is False
    assert status["knowledge_graph_mutation"] is False
