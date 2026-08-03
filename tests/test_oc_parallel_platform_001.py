from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.parallel_platform.routes import router
from app.parallel_platform.service import rank_candidates, score_matrix
from app.parallel_platform.contracts import IdentificationRequest, MatrixRequest


def test_matrix_excludes_unavailable_dimensions():
    result = score_matrix(
        MatrixRequest.model_validate(
            {
                "subject_taxon_id": "taxon:a",
                "object_taxon_id": "taxon:b",
                "dimensions": {
                    "taxonomy": {"score": 0.8, "weight": 2, "evidence": ["edge:1"]},
                    "ecology": {"score": 0.4, "weight": 1, "evidence": ["occurrence:1"]},
                    "pollinator": {"available": False},
                },
            }
        )
    )
    assert result["score"] == 0.666667
    assert next(item for item in result["dimensions"] if item["name"] == "pollinator")["score"] is None
    assert result["publication_authority"] is False


def test_identification_is_suggestion_only_and_exposes_next_observation():
    result = rank_candidates(
        IdentificationRequest.model_validate(
            {
                "observation_id": "obs:1",
                "features": {"lip_color": "white", "spur": "long"},
                "candidates": [
                    {
                        "taxon_id": "taxon:a",
                        "scientific_name": "Angraecum alpha",
                        "features": {"lip_color": "white", "spur": "long", "fragrance": "night"},
                    },
                    {
                        "taxon_id": "taxon:b",
                        "scientific_name": "Angraecum beta",
                        "features": {"lip_color": "yellow", "spur": "short"},
                    },
                ],
            }
        )
    )
    assert result["candidates"][0]["taxon_id"] == "taxon:a"
    assert result["next_best_observation"] == "fragrance"
    assert result["verified_identity"] is None


def test_routes_expose_versioned_contracts():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    capabilities = client.get("/api/platform/capabilities")
    homepage = client.get("/api/platform/homepage")
    assert capabilities.status_code == 200
    assert homepage.status_code == 200
    assert capabilities.json()["contract_version"] == "oc-parallel-v1"
    assert homepage.json()["governance"]["client_scoring_allowed"] is False
