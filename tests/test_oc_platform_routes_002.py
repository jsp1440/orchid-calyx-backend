from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_matrix_neighborhood_route_excludes_missing_evidence_from_score():
    response = client.post(
        "/api/platform/matrix/neighborhood",
        json={
            "subject_taxon_id": "taxon:a",
            "candidates": [
                {
                    "taxon_id": "taxon:b",
                    "accepted_name": "Example b",
                    "dimensions": {
                        "taxonomy": {
                            "availability": "available",
                            "score": 0.9,
                            "evidence": ["edge:1"],
                        },
                        "morphology": {"availability": "unavailable"},
                    },
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["neighbors"][0]["score"] == 0.9
    assert "morphology" in body["neighbors"][0]["unavailable_dimensions"]
    assert body["publication_authority"] is False


def test_identification_session_route_returns_suggestions_not_identity():
    response = client.post(
        "/api/platform/identification/session",
        json={
            "observation_id": "obs:1",
            "observations": [
                {"character": "flower_shape", "state": "observed", "value": "star"}
            ],
            "candidates": [
                {
                    "taxon_id": "taxon:1",
                    "scientific_name": "Example one",
                    "features": {"flower_shape": "star", "spur": "present"},
                    "evidence": ["source:1"],
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["candidates"][0]["fit_score"] == 1.0
    assert body["verified_identity"] is None
    assert body["publication_authority"] is False


def test_homepage_selection_rejects_unlicensed_image_and_keeps_server_authority():
    response = client.post(
        "/api/platform/homepage/select",
        json={
            "feature_type": "featured_species",
            "candidates": [
                {
                    "taxon_id": "taxon:1",
                    "scientific_name": "Example one",
                    "content_score": 0.95,
                    "source": "wikimedia",
                    "image_url": "https://example.invalid/image.jpg",
                    "image_license": None,
                    "image_attribution": "Photographer",
                }
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["availability"] == "unavailable"
    assert body["data"] is None
    assert body["publication_authority"] is False
