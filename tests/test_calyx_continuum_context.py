from __future__ import annotations

from types import SimpleNamespace

from app.calyx_conversation import continuum_context, speak_routes
from app.calyx_conversation.provider import DeterministicGovernedReplyProvider
from app.calyx_conversation.store import ConversationStore


def test_candidate_genera_extracts_botanical_names_without_prompt_noise():
    message = (
        "How should Cymbidium, Laelia, Epidendrum, Sobralia, Masdevallia, "
        "Lycaste, Paphiopedilum, and Phalaenopsis be managed during winter?"
    )
    assert continuum_context.candidate_genera(message) == [
        "Cymbidium",
        "Laelia",
        "Epidendrum",
        "Sobralia",
        "Masdevallia",
        "Lycaste",
        "Paphiopedilum",
        "Phalaenopsis",
    ]


def test_build_continuum_context_resolves_only_canonical_graph_taxa(monkeypatch):
    def graph(request):
        if request.genus == "Cymbidium":
            return {
                "found": True,
                "nodes": [{"canonical_key": "genus:cymbidium"}],
                "edges": [{"edge_type": "HAS_OCCURRENCE"}],
            }
        return {"found": False, "nodes": [], "edges": []}

    monkeypatch.setattr(continuum_context, "run_graph_context", graph)
    monkeypatch.setattr(
        continuum_context,
        "run_brain_query",
        lambda request: {"nodes": [{"canonical_key": "genus:cymbidium"}], "edges": []},
    )

    result = continuum_context.build_continuum_context(
        "Compare Cymbidium with Imaginaryorchid under wet winter conditions."
    )

    assert result["resolved_genera"] == ["Cymbidium"]
    assert result["taxa"][0]["knowledge_graph"]["edges"][0]["edge_type"] == "HAS_OCCURRENCE"
    assert result["read_only"] is True
    assert result["knowledge_graph_mutation"] is False


def test_speak_turn_passes_continuum_graph_context_to_reply(monkeypatch):
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
    monkeypatch.setattr(
        speak_routes,
        "build_continuum_context",
        lambda message: {
            "candidate_genera": ["Cymbidium"],
            "resolved_genera": ["Cymbidium"],
            "taxa": [
                {
                    "genus": "Cymbidium",
                    "knowledge_graph": {"found": True, "nodes": [{"id": 1}], "edges": [{"id": 2}]},
                    "brain_graph": {"nodes": [{"id": 1}], "edges": []},
                }
            ],
            "diagnostics": [],
            "read_only": True,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        },
    )
    monkeypatch.setattr(
        speak_routes,
        "BRAIN_MISSION_SERVICE",
        SimpleNamespace(
            start=lambda **kwargs: {
                "mission_id": "mission-empty",
                "state": "AWAITING_HUMAN_REVIEW",
                "sources": [],
                "supporting_evidence": [],
                "contradicting_evidence": [],
                "conclusions": [],
                "missing_evidence": [],
                "confidence": 0.0,
                "artifacts": {},
                "review_status": "HUMAN_REVIEW_REQUIRED",
                "publication_eligibility": {"eligible": False, "automatic_publication": False},
            }
        ),
    )

    auth = {"subject": "owner-a"}
    created = speak_routes.create_conversation(
        speak_routes.ConversationCreateRequest(project_id="wet-winter"), auth
    )
    result = speak_routes.append_turn(
        created["conversation_id"],
        speak_routes.ConversationTurnRequest(
            message="How should Cymbidium be managed during an unusually wet winter?"
        ),
        auth,
    )

    assert result["research"]["continuum"]["resolved_genera"] == ["Cymbidium"]
    assert "Orchid Continuum context" in result["answer"]
    assert "Cymbidium" in result["answer"]
    assert result["calyx_message"]["metadata"]["continuum_resolved_genera"] == ["Cymbidium"]
