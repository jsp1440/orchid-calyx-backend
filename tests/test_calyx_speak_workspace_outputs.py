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
    monkeypatch.setattr(
        speak_routes,
        "augment_retrieval_with_external_literature",
        lambda retrieval, message, limit: retrieval,
    )
    monkeypatch.setattr(
        speak_routes,
        "build_seasonal_climate_context",
        lambda message: {
            "requested": False,
            "status": "not_relevant",
            "products": [],
            "external": True,
            "time_sensitive": True,
        },
    )
    return store


def auth(subject: str) -> dict[str, str]:
    return {"subject": subject}


def create_for(subject: str, project_id: str = "vision") -> str:
    result = speak_routes.create_conversation(
        speak_routes.ConversationCreateRequest(title="Workspace outputs", project_id=project_id),
        auth(subject),
    )
    return result["conversation_id"]


def test_casual_turn_has_no_workspace_outputs(monkeypatch):
    conversation_id = create_for("owner-a")

    def forbidden_start(**kwargs):
        raise AssertionError("casual conversation must not launch a Brain mission")

    monkeypatch.setattr(speak_routes, "BRAIN_MISSION_SERVICE", SimpleNamespace(start=forbidden_start))
    result = speak_routes.append_turn(
        conversation_id, speak_routes.ConversationTurnRequest(message="Hello Calyx"), auth("owner-a"),
    )

    assert result["workspace_outputs"] == []


def test_mission_sources_become_a_grounded_table_output(monkeypatch):
    conversation_id = create_for("owner-a", "calyx-vision")

    def start(**kwargs):
        return {
            "mission_id": "mission-sources-1",
            "state": "AWAITING_HUMAN_REVIEW",
            "sources": [
                {"title": "Orchidaceae pollination syndromes", "object_type": "literature", "authorized_excerpt": "Bees are the primary pollinators."},
                {"title": "Cypripedium labellum morphology", "object_type": "taxon_record", "authorized_excerpt": None},
            ],
            "missing_evidence": [],
            "confidence": 0.81,
            "review_status": "HUMAN_REVIEW_REQUIRED",
            "publication_eligibility": {"eligible": False, "automatic_publication": False, "blockers": []},
        }

    monkeypatch.setattr(speak_routes, "BRAIN_MISSION_SERVICE", SimpleNamespace(start=start))
    result = speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(
            message="What pollinators are documented for Cypripedium?", research_mode="always",
        ),
        auth("owner-a"),
    )

    outputs = result["workspace_outputs"]
    sources_output = next(item for item in outputs if item["id"].endswith(":mission-sources"))
    assert sources_output["kind"] == "table"
    assert sources_output["provenance"]["evidence_status"] == "evidence"
    assert sources_output["provenance"]["source_module"] == "brain_mission"
    assert sources_output["provenance"]["source_id"] == "mission-sources-1"
    rows = sources_output["payload"]["rows"]
    assert rows[0]["title"] == "Orchidaceae pollination syndromes"
    assert rows[0]["excerpt"] == "Bees are the primary pollinators."
    assert rows[1]["excerpt"] == ""  # None excerpt must not crash or become the literal string "None"
    assert sources_output["created_at"] == result["calyx_message"]["created_at"]


def test_missing_evidence_becomes_an_explicit_unknown_status_output(monkeypatch):
    conversation_id = create_for("owner-a", "calyx-vision")

    def start(**kwargs):
        return {
            "mission_id": "mission-gap-1",
            "state": "AWAITING_HUMAN_REVIEW",
            "sources": [],
            "missing_evidence": ["controlled orchid-specific vision benchmark", "peer-reviewed pollinator census"],
            "confidence": 0.4,
            "review_status": "HUMAN_REVIEW_REQUIRED",
            "publication_eligibility": {"eligible": False, "automatic_publication": False, "blockers": []},
        }

    monkeypatch.setattr(speak_routes, "BRAIN_MISSION_SERVICE", SimpleNamespace(start=start))
    result = speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(message="What evidence is missing for this claim?", research_mode="always"),
        auth("owner-a"),
    )

    outputs = result["workspace_outputs"]
    gap_output = next(item for item in outputs if item["id"].endswith(":missing-evidence"))
    assert gap_output["kind"] == "text"
    assert gap_output["provenance"]["evidence_status"] == "unknown"
    assert "controlled orchid-specific vision benchmark" in gap_output["payload"]["body"]
    assert "peer-reviewed pollinator census" in gap_output["payload"]["body"]
    # No sources were returned, so no sources table should be fabricated.
    assert not any(item["id"].endswith(":mission-sources") for item in outputs)


def test_external_literature_citations_become_a_derived_status_table(monkeypatch):
    conversation_id = create_for("owner-a")

    def augmented(retrieval, message, limit):
        retrieval["external_literature"] = {
            "results": [
                {
                    "title": "Fungal associations in epiphytic orchids",
                    "authors": "Smith J",
                    "journal": "Mycological Research",
                    "doi": "10.1234/example",
                    "review_state": "REVIEW_REQUIRED",
                    "canonical_evidence": False,
                }
            ],
            "result_count": 1,
            "status": "ok",
        }
        return retrieval

    monkeypatch.setattr(speak_routes, "augment_retrieval_with_external_literature", augmented)
    result = speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(message="What fungal associations are documented for epiphytic orchids?"),
        auth("owner-a"),
    )

    outputs = result["workspace_outputs"]
    citation_output = next(item for item in outputs if item["id"].endswith(":external-citations"))
    assert citation_output["kind"] == "table"
    assert citation_output["provenance"]["evidence_status"] == "derived"
    assert citation_output["payload"]["rows"][0]["doi"] == "10.1234/example"


def test_workspace_outputs_never_contain_chart_or_image_kinds(monkeypatch):
    """This turn's evidence is never verified chart/image data - the module
    must never fabricate a visual kind to fill the workspace."""
    conversation_id = create_for("owner-a", "calyx-vision")

    def start(**kwargs):
        return {
            "mission_id": "mission-no-fab-1",
            "state": "AWAITING_HUMAN_REVIEW",
            "sources": [{"title": "A source", "object_type": "literature", "authorized_excerpt": "text"}],
            "missing_evidence": ["something"],
            "confidence": 0.5,
            "review_status": "HUMAN_REVIEW_REQUIRED",
            "publication_eligibility": {"eligible": False, "automatic_publication": False, "blockers": []},
        }

    monkeypatch.setattr(speak_routes, "BRAIN_MISSION_SERVICE", SimpleNamespace(start=start))
    result = speak_routes.append_turn(
        conversation_id,
        speak_routes.ConversationTurnRequest(message="Tell me about this orchid's ecology", research_mode="always"),
        auth("owner-a"),
    )

    kinds = {item["kind"] for item in result["workspace_outputs"]}
    assert kinds <= {"table", "text"}
    assert "chart" not in kinds
    assert "image" not in kinds
