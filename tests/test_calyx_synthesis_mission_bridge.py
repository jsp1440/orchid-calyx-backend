from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.calyx_conversation import routes
from app.calyx_conversation.routes import ResearchMissionRequest


class RecordingMissionService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def start(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "mission_id": "mission-1",
            "state": "AWAITING_HUMAN_REVIEW",
            "publication_eligibility": {
                "eligible": False,
                "automatic_publication": False,
                "blockers": ["HUMAN_REVIEW_REQUIRED"],
            },
        }


def test_gap_bridge_executes_existing_brain_mission_service(monkeypatch):
    service = RecordingMissionService()
    monkeypatch.setattr(routes, "_brain_mission_service", lambda: service)

    result = routes.start_synthesis_research_mission(
        "taxon-123",
        "pollination",
        ResearchMissionRequest(taxon_name="Laelia anceps", max_sources=8),
        {"actor": "owner-1"},
    )

    assert result["research_question"] == (
        "What are the pollination mechanisms and pollinators of Laelia anceps?"
    )
    assert result["review_required"] is True
    assert result["automatic_publication"] is False
    assert result["knowledge_graph_mutation"] is False
    assert service.calls[0]["tenant_id"] == "owner-1"
    assert service.calls[0]["actor"] == "owner-1"
    assert service.calls[0]["max_sources"] == 8
    assert str(service.calls[0]["project_id"]).startswith("calyx-gap-")


def test_gap_bridge_is_idempotently_scoped_by_taxon_and_domain(monkeypatch):
    service = RecordingMissionService()
    monkeypatch.setattr(routes, "_brain_mission_service", lambda: service)
    payload = ResearchMissionRequest(taxon_name="Laelia anceps")

    routes.start_synthesis_research_mission(
        "taxon-123", "habitat", payload, {"actor": "owner-1"}
    )
    routes.start_synthesis_research_mission(
        "taxon-123", "habitat", payload, {"actor": "owner-1"}
    )

    assert service.calls[0]["project_id"] == service.calls[1]["project_id"]
    assert service.calls[0]["question"] == service.calls[1]["question"]


def test_gap_bridge_normalizes_canonical_taxon_key(monkeypatch):
    service = RecordingMissionService()
    monkeypatch.setattr(routes, "_brain_mission_service", lambda: service)
    payload = ResearchMissionRequest(taxon_name="Laelia anceps")

    routes.start_synthesis_research_mission(
        " WorldPlants:123 ", "habitat", payload, {"actor": "owner-1"}
    )
    routes.start_synthesis_research_mission(
        "worldplants:123", "HABITAT", payload, {"actor": "owner-1"}
    )

    assert service.calls[0]["project_id"] == service.calls[1]["project_id"]


def test_gap_bridge_rejects_missing_canonical_taxon_id(monkeypatch):
    service = RecordingMissionService()
    monkeypatch.setattr(routes, "_brain_mission_service", lambda: service)

    with pytest.raises(HTTPException) as exc:
        routes.start_synthesis_research_mission(
            "   ",
            "habitat",
            ResearchMissionRequest(taxon_name="Laelia anceps"),
            {"actor": "owner-1"},
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "CANONICAL_TAXON_ID_REQUIRED"}
    assert service.calls == []


def test_gap_bridge_rejects_unknown_domain_without_starting_mission(monkeypatch):
    service = RecordingMissionService()
    monkeypatch.setattr(routes, "_brain_mission_service", lambda: service)

    with pytest.raises(HTTPException) as exc:
        routes.start_synthesis_research_mission(
            "taxon-123",
            "invented-domain",
            ResearchMissionRequest(taxon_name="Laelia anceps"),
            {"actor": "owner-1"},
        )

    assert exc.value.status_code == 422
    assert exc.value.detail == {"code": "UNSUPPORTED_SYNTHESIS_DOMAIN"}
    assert service.calls == []


def test_gap_bridge_requires_authenticated_actor(monkeypatch):
    service = RecordingMissionService()
    monkeypatch.setattr(routes, "_brain_mission_service", lambda: service)

    with pytest.raises(HTTPException) as exc:
        routes.start_synthesis_research_mission(
            "taxon-123",
            "literature",
            ResearchMissionRequest(taxon_name="Laelia anceps"),
            {},
        )

    assert exc.value.status_code == 401
    assert service.calls == []


def test_gap_bridge_capability_is_advertised():
    assert (
        "/api/calyx/synthesis/{taxon_id}/research-missions/{domain}"
        in routes.capabilities()["endpoints"]
    )
