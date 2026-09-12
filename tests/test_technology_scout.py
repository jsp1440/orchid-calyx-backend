from __future__ import annotations

import json
from contextlib import contextmanager

import pytest
from pydantic import ValidationError

from app.intake.technology_scout import (
    SCOUT_VERSION,
    TRIAGE_DIMENSIONS,
    ScoutBatch,
    ScoutMetadata,
    ingest_scout_batch,
    scout_intelligence_item,
    screen_metadata,
)


def metadata(**changes):
    return ScoutMetadata.model_validate(
        {
            "title": "Query-Adaptive Hybrid Search",
            "doi": "10.3390/make8040091",
            "primary_url": "https://doi.org/10.3390/make8040091",
            "discovery_url": "https://journalclub.io/episodes/query-adaptive-hybrid-search",
            "source_kind": "journalclub",
            **changes,
        }
    )


def test_cross_domain_search_is_relevant_without_orchid_keywords():
    result = screen_metadata(metadata())
    assert result["disposition"] == "RESEARCH_CANDIDATE"
    assert result["affected_modules"] == ["calyx", "literature", "research_station"]
    assert result["triage"]["orchid_relevance"]["state"] == "NO_METADATA_SIGNAL"
    assert result["triage"]["technology_relevance"]["state"] == "METADATA_SIGNAL"


def test_wheat_imaging_can_prompt_orchid_vision_investigation():
    result = screen_metadata(
        metadata(title="Multispectral disease classification in wheat")
    )
    assert "vision_lab" in result["affected_modules"]
    assert "conservatory" in result["affected_modules"]
    assert result["source_reported_findings"] == []
    assert all(
        "unmeasured" in hypothesis for hypothesis in result["transfer_hypotheses"]
    )


def test_complete_triage_never_fabricates_scores_from_metadata():
    result = screen_metadata(metadata())
    assert set(result["triage"]) == set(TRIAGE_DIMENSIONS)
    assert all(item["score"] is None for item in result["triage"].values())
    assert result["triage"]["evidence_quality"]["state"] == "UNASSESSED"
    assert result["triage"]["duplication"]["state"] == "UNASSESSED"
    assert result["assessment_basis"] == "METADATA_ONLY"
    assert result["canonical_graph_mutated"] is False
    assert result["engineering_dispatch_authorized"] is False
    assert result["provider_calls"] == 0


def test_no_rule_match_preserves_unknown_instead_of_rejecting_paper():
    result = screen_metadata(metadata(title="A new technique for protein folding"))
    assert result["disposition"] == "UNASSESSED"
    assert result["next_action"] == "REVIEW_METADATA"
    assert result["affected_modules"] == []


def test_terms_match_words_not_substrings():
    result = screen_metadata(metadata(title="Storage efficiency in floral tissue"))
    assert result["matched_methods"] == []  # 'rag' inside storage is not RAG.


def test_doi_identity_survives_different_titles_and_discovery_sources():
    first = scout_intelligence_item(metadata())
    second = scout_intelligence_item(
        metadata(
            title="New title",
            doi="DOI: 10.3390/MAKE8040091",
            source_kind="oc_harvester",
        )
    )
    assert first["knowledge_fingerprint"] == second["knowledge_fingerprint"]
    assert first["intelligence_id"] != second["intelligence_id"]
    assert first["lifecycle"] == second["lifecycle"] == "DISCOVERED"


def test_replay_identity_is_deterministic_and_keywords_are_normalized():
    first = scout_intelligence_item(metadata(keywords=["RAG", "retrieval", "RAG"]))
    second = scout_intelligence_item(metadata(keywords=["retrieval", "rag"]))
    assert first == second
    assert first["parser_version"] == SCOUT_VERSION


@pytest.mark.parametrize(
    "extra",
    [
        {"transcript": "restricted text"},
        {"full_text": "text"},
        {"automatic_dispatch": True},
    ],
)
def test_metadata_contract_rejects_content_and_authority_extensions(extra):
    with pytest.raises(ValidationError):
        metadata(**extra)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/paper",
        "https://user:secret@example.org",
        "file:///tmp/paper",
        "https://example.org/a b",
    ],
)
def test_unsafe_reference_shapes_are_rejected(url):
    with pytest.raises(ValidationError):
        metadata(primary_url=url)


def test_bounded_batch_and_keywords():
    with pytest.raises(ValidationError):
        ScoutBatch(items=[])
    with pytest.raises(ValidationError):
        ScoutBatch(items=[metadata()] * 51)
    with pytest.raises(ValidationError):
        metadata(keywords=["x" * 101])
    with pytest.raises(ValidationError):
        metadata(doi="not-a-doi")


def test_ingestion_uses_existing_source_and_ledger_without_extracting_claims(
    monkeypatch,
):
    from app.intake import intelligence_repository, repository

    sources = []
    observations = []

    def create_source(**kwargs):
        sources.append(kwargs)
        assert kwargs["extraction"].entities == []
        assert kwargs["extraction"].relationships == []
        assert kwargs["extraction"].tasks == []
        return {"id": 17}

    def record_items(**kwargs):
        observations.append(kwargs)
        return [{"id": 8, "lifecycle": "DISCOVERED", "new_observation": True}]

    monkeypatch.setattr(repository, "create_source", create_source)
    monkeypatch.setattr(
        intelligence_repository, "record_intelligence_items", record_items
    )
    result = ingest_scout_batch(ScoutBatch(items=[metadata()]))
    assert observations[0]["source_id"] == 17
    assert (
        json.loads(sources[0]["content"])
        == observations[0]["items"][0]["technology_scout"]
    )
    assert result["items"][0]["id"] == 8
    assert result["items"][0]["assessment"]["source"]["doi"] == "10.3390/make8040091"


def test_ledger_observation_keeps_assessment_and_does_not_reset_existing_lifecycle(
    monkeypatch,
):
    """Exercise real ledger SQL construction through its connection boundary."""
    from app.intake import intelligence_repository

    calls = []

    class Cursor:
        def execute(self, sql, params):
            calls.append((sql, params))

        def fetchone(self):
            sql = calls[-1][0]
            if "INSERT INTO oc_intake.intelligence_items" in sql:
                return {
                    "id": 11,
                    "knowledge_fingerprint": "existing-fingerprint",
                    "lifecycle": "REJECTED",
                    "knowledge_delta": "REQUIRES_REVIEW",
                    "observation_count": 1,
                    "last_seen_at": "existing",
                }
            if "INSERT INTO oc_intake.intelligence_observations" in sql:
                return {"id": 12}
            return {"observation_count": 2, "last_seen_at": "updated"}

    class Connection:
        @contextmanager
        def cursor(self):
            yield Cursor()

    @contextmanager
    def connect(*_args, **_kwargs):
        yield Connection()

    monkeypatch.setattr(intelligence_repository.psycopg, "connect", connect)
    item = scout_intelligence_item(metadata())
    result = intelligence_repository.record_intelligence_items(
        source_id=17, items=[item]
    )
    assert result[0]["lifecycle"] == "REJECTED"
    update = calls[0][0].split("DO UPDATE SET", 1)[1].split("RETURNING", 1)[0]
    assert "lifecycle" not in update
    assert "verification_required" not in update
    observation = next(
        params
        for sql, params in calls
        if "INSERT INTO oc_intake.intelligence_observations" in sql
    )
    assert observation[-1].obj["technology_scout"] == item["technology_scout"]
    assert observation[-1].obj["canonical_graph_mutated"] is False


def test_scout_api_keeps_owner_auth_and_validation(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.intake import routes

    monkeypatch.setenv("CALYX_API_KEY", "scout-test-key")
    calls = []

    def ingest(batch):
        calls.append(batch)
        return {"schema": SCOUT_VERSION, "items": [], "canonical_graph_mutated": False}

    monkeypatch.setattr(routes, "ingest_scout_batch", ingest)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    body = {"items": [metadata().model_dump()]}
    endpoint = "/api/intake/intelligence/scout"
    assert client.post(endpoint, json=body).status_code == 401
    assert calls == []
    headers = {"X-API-Key": "scout-test-key"}
    response = client.post(endpoint, json=body, headers=headers)
    assert response.status_code == 201
    assert len(calls) == 1
    assert response.json()["canonical_graph_mutated"] is False
    body["items"][0]["transcript"] = "not accepted"
    assert client.post(endpoint, json=body, headers=headers).status_code == 422
    assert len(calls) == 1
