from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import knowledge_explorer as api
from app.security import verify_owner_or_api_key
from runtime.knowledge_explorer import KnowledgeExplorerService


def _evidence(evidence_id: str, text: str) -> dict:
    return {
        "evidence_id": evidence_id,
        "source_uri": f"fixture://reviewed-botany/{evidence_id}",
        "source_title": "Reviewed botany fixture",
        "text": text,
        "locator": {"section": "fixture", "paragraph": evidence_id},
    }


def _register_fixture(service: KnowledgeExplorerService) -> None:
    service.register_candidate(
        {
            "concept_id": "aerial-root",
            "preferred_term": "aerial root",
            "synonyms": ["aerial roots"],
            "definitions": {
                "plain": "A root that develops above or outside the usual soil environment.",
                "learner": "An aerial root grows exposed to air or on a support rather than remaining buried in soil.",
                "advanced": "Aerial roots are roots occurring above the substrate or outside a conventional soil matrix and may show structural adaptations to exposed conditions.",
            },
            "evidence_spans": [
                _evidence("ev-aerial", "Fixture evidence describes exposed orchid roots as aerial roots.")
            ],
            "relationships": [],
        }
    )
    service.register_candidate(
        {
            "concept_id": "epiphytism",
            "preferred_term": "epiphytism",
            "synonyms": ["epiphytic habit"],
            "definitions": {
                "plain": "A growth habit in which a plant grows on another plant for physical support without rooting in the ground.",
                "learner": "Epiphytic orchids use another plant mainly as a place to grow rather than as a source of food.",
                "advanced": "Epiphytism is a non-parasitic growth habit in which a plant uses another plant as a physical substrate while obtaining water and nutrients independently.",
            },
            "evidence_spans": [
                _evidence("ev-epiphyte", "Fixture evidence describes epiphytism as growth on a supporting plant without parasitic nutrition.")
            ],
            "relationships": [],
        }
    )
    service.register_candidate(
        {
            "concept_id": "velamen",
            "preferred_term": "velamen",
            "synonyms": ["velamen radicum", "velamen tissue"],
            "definitions": {
                "plain": "A specialized outer tissue found on many exposed orchid roots.",
                "learner": "Velamen is a multilayered outer root covering that helps many orchids manage water around exposed roots.",
                "advanced": "Velamen is a specialized, typically multilayered outer root tissue associated with water uptake, retention, mechanical protection, and the exposed-root ecology of many orchids.",
            },
            "evidence_spans": [
                _evidence("ev-velamen-1", "Fixture evidence identifies velamen as specialized outer tissue on exposed orchid roots."),
                _evidence("ev-velamen-2", "Fixture evidence links velamen with water relations and protection of exposed roots."),
            ],
            "images": [
                {
                    "image_id": "velamen-root-image",
                    "source_uri": "fixture://licensed-media/velamen-root",
                    "license": "CC BY 4.0",
                    "attribution": "Fixture botanist",
                    "alt_text": "Close view of an orchid aerial root showing the pale outer root surface.",
                }
            ],
            "figures": [
                {
                    "figure_id": "velamen-root-figure",
                    "title": "Velamen on an aerial root",
                    "description": "Candidate educational figure linking the outer root tissue to an exposed orchid root.",
                    "image_id": "velamen-root-image",
                    "evidence_ids": ["ev-velamen-1", "ev-velamen-2"],
                }
            ],
            "relationships": [
                {
                    "predicate": "part_of",
                    "target_concept_id": "aerial-root",
                    "evidence_ids": ["ev-velamen-1"],
                },
                {
                    "predicate": "associated_with",
                    "target_concept_id": "epiphytism",
                    "evidence_ids": ["ev-velamen-2"],
                },
            ],
        }
    )


def test_velamen_fixture_preserves_multilevel_evidence_image_figure_and_relationships(tmp_path: Path):
    service = KnowledgeExplorerService(tmp_path / "explorer")
    _register_fixture(service)
    concept = service.get("velamen")
    assert concept["preferred_term"] == "velamen"
    assert set(concept["definitions"]) == {"plain", "learner", "advanced"}
    assert len(concept["evidence_spans"]) == 2
    assert all(len(item["checksum_sha256"]) == 64 for item in concept["evidence_spans"])
    assert concept["images"][0]["license"] == "CC BY 4.0"
    assert concept["images"][0]["alt_text"]
    assert concept["figures"][0]["evidence_ids"] == ["ev-velamen-1", "ev-velamen-2"]
    assert {item["target_concept_id"] for item in concept["relationships"]} == {
        "aerial-root",
        "epiphytism",
    }
    assert concept["candidate_only"] is True
    assert concept["scientific_review_required"] is True
    assert concept["scientific_publication_authorized"] is False
    assert concept["knowledge_graph_mutation_authorized"] is False


def test_synonym_resolution_and_popover_levels_are_deterministic(tmp_path: Path):
    service = KnowledgeExplorerService(tmp_path / "explorer")
    _register_fixture(service)
    resolved = service.resolve("Velamen radicum")
    assert resolved["state"] == "matched"
    assert resolved["concept_id"] == "velamen"
    plain = service.popover("velamen", level="plain")
    learner = service.popover("velamen tissue", level="learner")
    advanced = service.popover("velamen", level="advanced")
    assert plain["popover"]["definition_level"] == "plain"
    assert learner["popover"]["definition_level"] == "learner"
    assert advanced["popover"]["definition_level"] == "advanced"
    assert len({plain["popover"]["definition"], learner["popover"]["definition"], advanced["popover"]["definition"]}) == 3
    assert service.resolve("unknown orchid concept")["state"] == "unmatched"


def test_expanded_response_resolves_two_connected_concepts(tmp_path: Path):
    service = KnowledgeExplorerService(tmp_path / "explorer")
    _register_fixture(service)
    expanded = service.expanded("velamen")
    connected = {item["target_concept_id"]: item for item in expanded["connected_concepts"]}
    assert connected["aerial-root"]["target_preferred_term"] == "aerial root"
    assert connected["epiphytism"]["target_preferred_term"] == "epiphytism"
    assert all(item["target_available"] for item in connected.values())
    assert expanded["candidate_only"] is True
    assert expanded["scientific_review_required"] is True


def test_invalid_evidence_figure_image_and_relationship_fail_closed(tmp_path: Path):
    service = KnowledgeExplorerService(tmp_path / "explorer")
    base = {
        "concept_id": "bad-concept",
        "preferred_term": "bad concept",
        "definitions": {"plain": "p", "learner": "l", "advanced": "a"},
        "evidence_spans": [_evidence("ev-1", "fixture evidence")],
    }
    bad_figure = {
        **base,
        "figures": [
            {
                "figure_id": "fig-1",
                "title": "Bad",
                "description": "Unknown evidence fixture",
                "evidence_ids": ["missing-evidence"],
            }
        ],
    }
    try:
        service.register_candidate(bad_figure)
    except ValueError as exc:
        assert "KNOWLEDGE_FIGURE_EVIDENCE_UNKNOWN" in str(exc)
    else:
        raise AssertionError("figure with unknown evidence must fail")

    bad_relationship = {
        **base,
        "relationships": [
            {
                "predicate": "causes_taxonomy_activation",
                "target_concept_id": "anything",
                "evidence_ids": ["ev-1"],
            }
        ],
    }
    try:
        service.register_candidate(bad_relationship)
    except ValueError as exc:
        assert "KNOWLEDGE_RELATIONSHIP_INVALID" in str(exc)
    else:
        raise AssertionError("unsupported scientific relationship must fail")

    bad_image = {
        **base,
        "images": [
            {
                "image_id": "img-1",
                "source_uri": "fixture://image",
                "license": "CC BY 4.0",
                "attribution": "Fixture",
                "alt_text": "",
            }
        ],
    }
    try:
        service.register_candidate(bad_image)
    except ValueError as exc:
        assert "KNOWLEDGE_IMAGE_FIELDS_REQUIRED" in str(exc)
    else:
        raise AssertionError("image without alt text must fail")


def test_readiness_reports_candidate_only_non_authority(tmp_path: Path):
    service = KnowledgeExplorerService(tmp_path / "explorer")
    _register_fixture(service)
    readiness = service.readiness()
    assert readiness["concepts"] == 3
    assert readiness["evidence_spans"] == 4
    assert readiness["relationships"] == 2
    assert readiness["candidate_only"] is True
    assert readiness["scientific_review_required"] is True
    assert readiness["scientific_publication_authorized"] is False
    assert readiness["production_deployment_authorized"] is False
    assert readiness["knowledge_graph_mutation_authorized"] is False


def test_protected_api_returns_compact_and_expanded_payloads(tmp_path: Path, monkeypatch):
    service = KnowledgeExplorerService(tmp_path / "explorer")
    _register_fixture(service)
    monkeypatch.setattr(api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "reviewer", "auth_type": "test"}
    client = TestClient(app)

    popover = client.get("/brain/mission-control/knowledge-explorer/popover/velamen?level=learner")
    assert popover.status_code == 200
    assert popover.json()["popover"]["definition_level"] == "learner"
    expanded = client.get("/brain/mission-control/knowledge-explorer/concepts/velamen")
    assert expanded.status_code == 200
    assert len(expanded.json()["connected_concepts"]) == 2
    readiness = client.get("/brain/mission-control/knowledge-explorer/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["decision"] == "KNOWLEDGE_EXPLORER_REVIEW_READY"
