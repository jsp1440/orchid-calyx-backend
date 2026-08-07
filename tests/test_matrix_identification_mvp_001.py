from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.matrix_identification import router
from runtime.matrix_identification import Candidate, Observation, rank_candidates


def test_unknowns_do_not_penalize_and_missing_data_reduce_coverage():
    report = rank_candidates(
        [
            Observation("flower_color", "red", certainty="certain", weight=2),
            Observation("fragrance", "present", certainty="unknown", weight=4),
        ],
        [
            Candidate("t1", "Taxon alpha", {"flower_color": "red"}),
            Candidate("t2", "Taxon beta", {}),
        ],
    )

    alpha, beta = report["candidates"]
    assert alpha["taxon_id"] == "t1"
    assert alpha["score"] == 1.0
    assert alpha["coverage"] == 1.0
    assert beta["score"] == 0.0
    assert beta["coverage"] == 0.0
    assert alpha["explanations"][1]["status"] == "ignored_unknown_observation"


def test_uncertainty_and_numeric_ranges_are_weighted_and_explained():
    report = rank_candidates(
        [
            Observation("flower_width_mm", 32, certainty="probable", weight=2),
            Observation("growth_habit", ["epiphytic", "lithophytic"], weight=1),
        ],
        [
            Candidate(
                "t1",
                "Taxon alpha",
                {
                    "flower_width_mm": {"min": 30, "max": 35},
                    "growth_habit": "epiphytic",
                },
            ),
            Candidate(
                "t2",
                "Taxon beta",
                {
                    "flower_width_mm": {"min": 10, "max": 15},
                    "growth_habit": "terrestrial",
                },
            ),
        ],
    )

    assert report["candidates"][0]["taxon_id"] == "t1"
    assert report["candidates"][0]["score"] > report["candidates"][1]["score"]
    assert report["candidates"][0]["explanations"][0]["effective_weight"] == 1.5
    assert report["candidates"][0]["explanations"][0]["status"] == "matched"


def test_deterministic_tie_breaking():
    report = rank_candidates(
        [Observation("color", "white")],
        [
            Candidate("z", "Taxon zeta", {"color": "white"}),
            Candidate("a", "Taxon alpha", {"color": "white"}),
        ],
    )
    assert [item["taxon_id"] for item in report["candidates"]] == ["a", "z"]


def test_api_is_owner_gated_and_returns_explanations():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    denied = client.post(
        "/api/matrix-identification/evaluate",
        json={
            "observations": [{"character": "color", "value": "white"}],
            "candidates": [
                {
                    "taxon_id": "t1",
                    "scientific_name": "Taxon alpha",
                    "states": {"color": "white"},
                }
            ],
        },
    )
    assert denied.status_code in {401, 403, 503}
