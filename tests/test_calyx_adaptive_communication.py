from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.calyx_conversation import reasoning_routes
from app.calyx_conversation.adaptive_communication import (
    ScientificFirewallError,
    VoiceProfile,
    protected_segments_from_answer,
    render_adaptive_answer,
    verify_scientific_firewall,
)
from app.calyx_conversation.reasoning_routes import (
    CalyxReasoningMapRequest,
    compose_reasoning_answer,
    run_reasoning_map,
)
from app.security import verify_owner_or_api_key
from runtime.knowledge_graph import Edge, InMemoryGraphRepository, Node


def graph() -> InMemoryGraphRepository:
    return InMemoryGraphRepository(
        nodes=[
            Node(1, "environment", "environment:cool-night", "Cool night"),
            Node(2, "physiology", "physiology:respiration", "Respiration"),
            Node(3, "phenotype", "phenotype:flowering", "Flowering"),
        ],
        edges=[
            Edge(1, "reduces", 1, 2, "paper_claim", "p1", "curated", 0.90, "high"),
            Edge(2, "promotes", 2, 3, "paper_claim", "p2", "curated", 0.80, "high"),
        ],
    )


def retrieval() -> dict:
    return {
        "results": [
            {
                "title": "Temperature and flowering physiology",
                "object_type": "paper",
                "verification_state": "verified",
                "citation": {"document_title": "Orchid Physiology Review"},
            }
        ],
        "total_eligible_results": 1,
        "retrieval_mode": "HYBRID",
        "ranking_configuration_version": "test",
    }


def canonical_answer(monkeypatch) -> str:
    monkeypatch.setattr(reasoning_routes, "_graph_repository", graph)
    reasoning = run_reasoning_map(CalyxReasoningMapRequest(subject_node_id=1))
    return compose_reasoning_answer(
        "Why might cool nights affect flowering?",
        reasoning,
        retrieval(),
        pathway_limit=5,
    )


def client(monkeypatch) -> TestClient:
    application = FastAPI()
    application.include_router(reasoning_routes.router)
    application.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "tester"
    }
    monkeypatch.setattr(reasoning_routes, "_graph_repository", graph)
    monkeypatch.setattr(
        reasoning_routes,
        "_retrieval",
        lambda message, mode, limit, internal_access: retrieval(),
    )
    return TestClient(application)


@pytest.mark.parametrize("audience", ["grower", "student", "researcher"])
def test_profiles_preserve_all_protected_scientific_segments(monkeypatch, audience):
    canonical = canonical_answer(monkeypatch)
    rendered = render_adaptive_answer(
        canonical,
        VoiceProfile(audience=audience, teaching_mode=audience == "student"),
    )

    assert rendered.firewall_passed is True
    assert rendered.fallback_used is False
    assert rendered.mode == "deterministic"
    assert rendered.answer != canonical
    for segment in protected_segments_from_answer(canonical):
        assert segment in rendered.answer


def test_grower_student_and_researcher_have_distinct_framing(monkeypatch):
    canonical = canonical_answer(monkeypatch)
    grower = render_adaptive_answer(canonical, VoiceProfile(audience="grower")).answer
    student = render_adaptive_answer(
        canonical, VoiceProfile(audience="student", teaching_mode=True)
    ).answer
    researcher = render_adaptive_answer(
        canonical, VoiceProfile(audience="researcher")
    ).answer

    assert "practical interpretation" in grower
    assert "How the reasoning connects:" in student
    assert "assembled the current inspectable causal pathways" in researcher
    assert len({grower, student, researcher}) == 3


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("Reasoning map: 3 nodes", "Reasoning map: 4 nodes"),
        ("confidence=0.900", "confidence=0.990"),
        ("Temperature and flowering physiology", "Different paper"),
        ("[verified]", "[unverified]"),
        ("not proof of causality", "proof of causality"),
    ],
)
def test_firewall_rejects_mutated_scientific_content(monkeypatch, old, new):
    canonical = canonical_answer(monkeypatch)
    assert old in canonical
    mutated = canonical.replace(old, new, 1)

    with pytest.raises(ScientificFirewallError):
        verify_scientific_firewall(canonical, mutated)


def test_reasoning_query_voice_profile_is_provider_free_end_to_end(monkeypatch):
    response = client(monkeypatch).post(
        "/calyx/reasoning-query",
        json={
            "message": "Why might cool nights affect flowering?",
            "subject_node_id": 1,
            "voice_profile": {
                "audience": "grower",
                "expertise_level": "intermediate",
                "verbosity": "concise",
                "technical_depth": "medium",
                "teaching_mode": False,
                "conversationality": "high",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["communication"]["provider_free"] is True
    assert payload["communication"]["mode"] == "deterministic"
    assert payload["communication"]["scientific_firewall_passed"] is True
    assert payload["communication"]["fallback_used"] is False
    assert payload["communication"]["profile"]["audience"] == "grower"
    assert "practical interpretation" in payload["answer"]
    assert "confidence=0.900" in payload["answer"]
    assert "Temperature and flowering physiology" in payload["answer"]


def test_no_voice_profile_preserves_canonical_answer(monkeypatch):
    api = client(monkeypatch)
    response = api.post(
        "/calyx/reasoning-query",
        json={
            "message": "Why might cool nights affect flowering?",
            "subject_node_id": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    reasoning = run_reasoning_map(CalyxReasoningMapRequest(subject_node_id=1))
    expected = compose_reasoning_answer(
        "Why might cool nights affect flowering?",
        reasoning,
        retrieval(),
        pathway_limit=5,
    )
    assert payload["answer"] == expected
    assert payload["communication"] == {
        "mode": "canonical",
        "profile": None,
        "scientific_firewall_passed": True,
        "fallback_used": False,
        "provider_free": True,
    }
