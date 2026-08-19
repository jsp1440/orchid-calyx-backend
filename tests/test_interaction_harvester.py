from __future__ import annotations

import runtime.interaction_harvester as interactions
from app.calyx_conversation.interaction_discovery_ingest import (
    document_from_globi_interaction,
)


def test_globi_document_is_review_bound() -> None:
    document = document_from_globi_interaction(
        {
            "source_taxon_name": "Orchis mascula",
            "source_taxon_external_id": "GBIF:123",
            "interaction_type": "pollinatedBy",
            "target_taxon_name": "Bombus terrestris",
            "target_taxon_external_id": "GBIF:456",
            "study_citation": "Example study",
            "study_external_id": "doi:10.1234/example",
        },
        query_role="source",
    )
    assert document is not None
    assert document.metadata["interaction_type"] == "pollinatedBy"
    assert document.metadata["scientific_review_required"] is True
    assert document.metadata["automatic_publication"] is False
    assert document.metadata["knowledge_graph_mutation"] is False
    assert document.metadata["stable_research_snapshot_preferred"] is True


def test_globi_lane_not_due_without_network(monkeypatch) -> None:
    monkeypatch.setattr(
        interactions.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network called")),
    )
    result = interactions.harvest_interactions_once(limit=20, now=900)
    assert result["status"] == "not_due"


def test_globi_due_query_is_bounded_and_includes_orchid_children(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return [
                {
                    "source_taxon_name": "Orchis mascula",
                    "source_taxon_external_id": "GBIF:123",
                    "interaction_type": "pollinatedBy",
                    "target_taxon_name": "Bombus terrestris",
                    "target_taxon_external_id": "GBIF:456",
                    "study_citation": "Example study",
                }
            ]

    def fake_get(url, *, params, timeout, headers):
        captured.update(params)
        assert url == interactions.GLOBI_INTERACTION_URL
        assert timeout == 20
        return FakeResponse()

    def fake_ingest(rows, *, query_role: str):
        assert query_role == "source"
        assert len(rows) == 1
        return {"status": "indexed_for_research", "indexed": 1}

    monkeypatch.setattr(interactions.requests, "get", fake_get)
    monkeypatch.setattr(interactions, "ingest_globi_interactions_for_research", fake_ingest)

    result = interactions.harvest_interactions_once(limit=100, now=0)

    assert captured["sourceTaxon"] == "Orchidaceae"
    assert "excludeChildTaxa" not in captured
    assert captured["includeObservations"] == "true"
    assert captured["type"] == "json.v2"
    assert captured["limit"] == 25
    assert result["indexed"] == 1
    assert result["automatic_publication"] is False
