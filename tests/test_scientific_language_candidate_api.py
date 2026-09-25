from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.literature_extraction.models import GlossaryTerm, Provenance
from app.literature_extraction.routes import get_literature_repository
from app.main import app
from app.scientific_synthesis import language_routes
from app.scientific_synthesis.glossary_candidates import (
    JsonGlossaryCandidateRepository,
)


class FakeConceptService:
    def search_concepts(self, query: str, *, language=None, limit=25):
        resolved = query.casefold() == "labellum"
        return {
            "query": query,
            "resolution": "RESOLVED" if resolved else "UNRESOLVED",
            "exact_concept_ids": ["concept-labellum"] if resolved else [],
            "matches": [{"label": "labellum"}] if resolved else [],
        }


class FakeLiteratureRepository:
    def __init__(self, paper):
        self.paper = paper

    def get(self, paper_id):
        return self.paper if paper_id == self.paper.paper_id else None


def _term(value: str) -> GlossaryTerm:
    return GlossaryTerm(
        term_id=f"term:{value.casefold()}",
        term=value,
        normalized_term=value.casefold(),
        status="candidate",
        provenance=Provenance(
            method="rule_extracted",
            confidence=0.9,
            extractor="glossary-rules",
            extractor_version="1",
        ),
    )


def test_authenticated_candidate_intake_replays_and_lists_after_restart(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CALYX_API_KEY", "test-key")
    monkeypatch.setattr(
        language_routes,
        "get_concept_service",
        lambda: FakeConceptService(),
    )
    paper = SimpleNamespace(
        paper_id="paper-1",
        source=SimpleNamespace(content_hash="a" * 64),
        glossary_terms=[_term("Labellum"), _term("Pseudobulb")],
    )
    repository = JsonGlossaryCandidateRepository(tmp_path)
    app.dependency_overrides[get_literature_repository] = lambda: (
        FakeLiteratureRepository(paper)
    )
    app.dependency_overrides[
        language_routes.get_glossary_candidate_repository
    ] = lambda: repository

    try:
        with TestClient(app) as client:
            path = "/api/scientific-interpretation/language/papers/paper-1/candidates"
            assert client.post(path).status_code == 401
            first = client.post(path, headers={"X-API-Key": "test-key"})
            replay = client.post(path, headers={"X-API-Key": "test-key"})
            listing = client.get(
                "/api/scientific-interpretation/language/candidates",
                headers={"X-API-Key": "test-key"},
            )
            matched = client.get(
                "/api/scientific-interpretation/language/candidates",
                params={"state": "MATCHED_PENDING_REVIEW"},
                headers={"X-API-Key": "test-key"},
            )
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 201
    assert first.json()["created_count"] == 2
    assert replay.status_code == 201
    assert replay.json()["created_count"] == 0
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert matched.json()["total"] == 1
    item = matched.json()["items"][0]
    assert item["term"] == "Labellum"
    assert item["source_hash"] == "a" * 64
    assert item["source_provenance"]["extractor"] == "glossary-rules"
    assert item["review_required"] is True
    assert item["canonical_promotion_authorized"] is False
    assert item["knowledge_graph_publication_authorized"] is False
    assert JsonGlossaryCandidateRepository(tmp_path).list()


def test_candidate_lookup_is_authenticated_and_missing_is_explicit(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("CALYX_API_KEY", "test-key")
    app.dependency_overrides[
        language_routes.get_glossary_candidate_repository
    ] = lambda: JsonGlossaryCandidateRepository(tmp_path)
    candidate_id = "a" * 64

    try:
        with TestClient(app) as client:
            path = f"/api/scientific-interpretation/language/candidates/{candidate_id}"
            assert client.get(path).status_code == 401
            response = client.get(path, headers={"X-API-Key": "test-key"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Glossary candidate not found"
