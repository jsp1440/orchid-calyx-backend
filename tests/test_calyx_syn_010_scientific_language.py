from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.concepts.dependencies import get_concept_service
from app.literature_extraction.models import GlossaryTerm, Provenance
from app.literature_extraction.routes import get_literature_repository
from app.main import app
from app.scientific_synthesis.language import BotanicalLanguageService


class FakeConceptService:
    def search_concepts(self, query: str, *, language=None, limit=25):
        return {
            "query": query,
            "normalized_query": query.casefold(),
            "resolution": "RESOLVED" if query.casefold() == "labellum" else "UNRESOLVED",
            "exact_concept_ids": ["11111111-1111-1111-1111-111111111111"]
            if query.casefold() == "labellum"
            else [],
            "matches": [{"label": "labellum"}] if query.casefold() == "labellum" else [],
        }


class FakeLiteratureRepository:
    def __init__(self, paper):
        self.paper = paper

    def get(self, paper_id):
        return self.paper if paper_id == self.paper.paper_id else None


def _term(value: str) -> GlossaryTerm:
    return GlossaryTerm(
        term_id=f"term:{value}",
        term=value,
        normalized_term=value.casefold(),
        status="candidate",
        provenance=Provenance(method="rule_extracted", confidence=1.0),
    )


def test_word_root_analysis_is_conservative_and_multilingual():
    service = BotanicalLanguageService()
    pseudobulb = service.analyze_term("pseudobulb")
    gynostemium = service.analyze_term("gynostemium")

    assert any(item["meaning"].startswith("false") for item in pseudobulb["word_elements"])
    assert any(item["language"] == "Greek" for item in gynostemium["word_elements"])
    assert all(
        item["analysis_state"] == "MORPHOLOGICAL_HINT"
        for item in pseudobulb["word_elements"] + gynostemium["word_elements"]
    )
    assert pseudobulb["etymology_review_required"] is True


def test_botanical_latin_background_distinguishes_name_from_identification():
    result = BotanicalLanguageService().analyze_term("alba")
    principles = " ".join(result["botanical_latin"]["principles"])

    assert "specific epithet" in principles
    assert "identification" in principles
    assert "gender" in principles


def test_paper_language_endpoint_connects_extracted_glossary_to_concept_registry(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", "test-key")
    paper = SimpleNamespace(
        paper_id="paper-1",
        source=SimpleNamespace(content_hash="source-hash-1234567890"),
        glossary_terms=[_term("labellum"), _term("pseudobulb")],
    )
    app.dependency_overrides[get_literature_repository] = lambda: FakeLiteratureRepository(paper)
    app.dependency_overrides[get_concept_service] = lambda: FakeConceptService()

    try:
        with TestClient(app) as client:
            path = "/api/scientific-interpretation/language/papers/paper-1"
            assert client.get(path).status_code == 401
            response = client.get(path, headers={"X-API-Key": "test-key"})
    finally:
        app.dependency_overrides.pop(get_literature_repository, None)
        app.dependency_overrides.pop(get_concept_service, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 2
    assert payload["glossary_source"] == "literature_extraction.glossary_terms"
    labellum = next(item for item in payload["items"] if item["term"] == "labellum")
    assert labellum["concept_registry"]["resolution"] == "RESOLVED"
    assert labellum["glossary"]["status"] == "candidate"
    assert payload["canonical_concept_promotion"] is False


def test_word_element_dictionary_and_background_apis_are_authenticated(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", "test-key")
    app.dependency_overrides[get_concept_service] = lambda: FakeConceptService()
    try:
        with TestClient(app) as client:
            root = "/api/scientific-interpretation/language"
            assert client.get(f"{root}/word-elements").status_code == 401
            words = client.get(
                f"{root}/word-elements?q=leaf", headers={"X-API-Key": "test-key"}
            )
            latin = client.get(
                f"{root}/botanical-latin", headers={"X-API-Key": "test-key"}
            )
    finally:
        app.dependency_overrides.pop(get_concept_service, None)

    assert words.status_code == 200
    assert words.json()["count"] >= 1
    assert latin.status_code == 200
    assert latin.json()["title"].startswith("Botanical Latin")
