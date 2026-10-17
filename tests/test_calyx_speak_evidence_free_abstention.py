"""An evidence-free scientific turn is never answered from provider memory.

When canonical retrieval, external literature, the knowledge bridge and the
Brain mission all come back empty, the Speak path answers with the
deterministic governed composer, which states the gap, instead of spending a
generative (paid) turn on an answer that could only come from the provider's
own memory. Everything runs in-process; the generative provider is a fake
that records whether it was called.
"""

from __future__ import annotations

import pytest

from app.calyx_conversation import speak_routes
from app.calyx_conversation.access_economics import CEILING_ENV, CalyxAccessPolicy
from app.calyx_conversation.provider import (
    DeterministicGovernedReplyProvider,
    GeneratedReply,
)
from app.calyx_conversation.store import ConversationStore
from runtime.research_station_store import MemoryProjectRecordStore

PRIVILEGED = {"actor": "backend_api_key", "auth_type": "api_key"}
QUESTION = "Which pollinators are reported for Ophrys apifera and how strong is that evidence?"


class FakeGenerativeProvider:
    provider_name = "fake-generative"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *, messages, governed_context) -> GeneratedReply:
        self.calls += 1
        return GeneratedReply(
            text="fluent answer from provider memory",
            provider=self.provider_name,
            model=self.model_name,
            request_hash="h" * 64,
        )


@pytest.fixture()
def provider(monkeypatch):
    fake = FakeGenerativeProvider()
    monkeypatch.setattr(speak_routes, "STORE", ConversationStore(dsn=""))
    monkeypatch.setattr(speak_routes, "configured_reply_provider", lambda: fake)
    monkeypatch.setattr(
        speak_routes,
        "_retrieval",
        lambda message, mode, limit, internal_access: {
            "results": [],
            "total_eligible_results": 0,
            "retrieval_mode": mode,
        },
    )
    monkeypatch.setattr(
        speak_routes, "augment_retrieval_with_external_literature", lambda retrieval, message, limit: retrieval
    )
    monkeypatch.setattr(
        speak_routes,
        "build_seasonal_climate_context",
        lambda message: {"requested": False, "status": "not_relevant", "products": []},
    )
    monkeypatch.setattr(
        speak_routes,
        "_safe_knowledge_context",
        lambda message: {"lexicon": {"matched_terms": 0}, "literature": {"matched_papers": 0}},
    )
    monkeypatch.setattr(
        speak_routes,
        "ACCESS_POLICY",
        CalyxAccessPolicy(env={CEILING_ENV: "5"}, store=MemoryProjectRecordStore()),
    )
    return fake


def turn(message: str = QUESTION) -> dict:
    conversation_id = speak_routes.create_conversation(
        speak_routes.ConversationCreateRequest(project_id="pollination"), PRIVILEGED
    )["conversation_id"]
    request = speak_routes.ConversationTurnRequest(message=message, research_mode="never")
    return speak_routes.append_turn(conversation_id, request, PRIVILEGED)


def test_evidence_free_turn_is_not_sent_to_the_generative_provider(provider):
    result = turn()
    assert provider.calls == 0
    assert result["provider"]["name"] == DeterministicGovernedReplyProvider.provider_name
    assert result["provider"]["generative"] is False
    assert result["access_policy"]["provider_outcome"] == "deterministic_insufficient_evidence"
    assert result["access_policy"]["generative_allowed"] is True  # entitled, but nothing to ground it
    assert result["access_policy"]["reserved"] == []  # no paid turn was spent
    assert result["epistemic_policy"]["evidence_free_turns_use_generative_provider"] is False
    assert result["research"]["retrieval"]["conversation_synthesis_mode"] == "insufficient_evidence_retrieval_gap"
    assert "fluent answer from provider memory" not in result["answer"]
    assert "can't answer that from evidence" in result["answer"]


def test_evidence_free_turns_do_not_consume_the_program_ceiling(provider):
    for _ in range(7):
        assert turn()["access_policy"]["reserved"] == []
    assert provider.calls == 0


def test_knowledge_bridge_literature_counts_as_evidence(provider, monkeypatch):
    monkeypatch.setattr(
        speak_routes,
        "_safe_knowledge_context",
        lambda message: {"lexicon": {"matched_terms": 0}, "literature": {"matched_papers": 2}},
    )
    result = turn()
    assert provider.calls == 1
    assert result["access_policy"]["provider_outcome"] == "generative"


def test_casual_turn_is_unaffected(provider):
    result = turn("Hello Calyx")
    assert result["access_policy"]["provider_outcome"] != "deterministic_insufficient_evidence"


@pytest.mark.parametrize(
    "retrieval,knowledge,mission,expected",
    [
        ({"results": []}, {}, None, True),
        ({"results": [{"id": 1}]}, {}, None, False),
        ({"results": [], "external_literature": {"results": [{"id": "x"}]}}, {}, None, False),
        ({"results": []}, {"literature": {"matched_papers": 1}}, None, False),
        ({"results": []}, {}, {"mission_id": "m"}, False),
    ],
)
def test_evidence_free_turn_rule(retrieval, knowledge, mission, expected):
    assert (
        speak_routes._evidence_free_turn(casual=False, retrieval=retrieval, knowledge=knowledge, mission=mission)
        is expected
    )
    assert speak_routes._evidence_free_turn(casual=True, retrieval=retrieval, knowledge=knowledge, mission=mission) is False
