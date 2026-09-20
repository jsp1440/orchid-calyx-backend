import json

from fastapi.testclient import TestClient

from app.concepts.dependencies import get_concept_service
from app.main import app
from app.scientific_synthesis.figure_requests import JsonFigureRequestRepository
from app.scientific_synthesis.language_routes import get_figure_request_repository
from app.security import verify_owner_or_api_key

CONCEPT_ID = "2b16acee-3af8-4f87-8acd-e4f7c8f5db1b"


class FakeConceptService:
    def __init__(self, *, status="ACTIVE", review_state="APPROVED"):
        self.status = status
        self.review_state = review_state

    def get_concept(self, identifier):
        if str(identifier) == "00000000-0000-0000-0000-000000000000":
            raise LookupError("CONCEPT_NOT_FOUND")
        return {
            "concept_id": str(identifier),
            "status": self.status,
            "review_state": self.review_state,
        }


def _payload(request_type="DIAGRAM"):
    return {
        "concept_id": CONCEPT_ID,
        "request_type": request_type,
        "production_brief": "  Compare the labellum orientation   before and after resupination. ",
        "source_provenance": {
            "source_ref": "paper:resupination-review:figure-2",
            "source_hash": "a" * 64,
            "citation": "Example et al. (2025), figure 2.",
        },
    }


def _client(tmp_path, service=None):
    app.dependency_overrides[get_figure_request_repository] = lambda: (
        JsonFigureRequestRepository(tmp_path)
    )
    app.dependency_overrides[get_concept_service] = lambda: (
        service or FakeConceptService()
    )
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "test-owner"
    }
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.pop(get_figure_request_repository, None)
    app.dependency_overrides.pop(get_concept_service, None)
    app.dependency_overrides.pop(verify_owner_or_api_key, None)


def test_figure_queue_requires_authentication(monkeypatch, tmp_path):
    monkeypatch.setenv("CALYX_API_KEY", "test-key")
    app.dependency_overrides[get_figure_request_repository] = lambda: (
        JsonFigureRequestRepository(tmp_path)
    )
    app.dependency_overrides[get_concept_service] = lambda: FakeConceptService()
    with TestClient(app) as client:
        unauthorized = client.post(
            "/api/scientific-interpretation/language/figure-requests",
            json=_payload(),
        )
        authorized = client.post(
            "/api/scientific-interpretation/language/figure-requests",
            json=_payload(),
            headers={"X-API-Key": "test-key"},
        )
    assert unauthorized.status_code == 401
    assert authorized.status_code == 201


def test_create_replay_restart_and_filter_preserve_exact_provenance(tmp_path):
    with _client(tmp_path) as client:
        first = client.post(
            "/api/scientific-interpretation/language/figure-requests",
            json=_payload(),
        )
        replay = client.post(
            "/api/scientific-interpretation/language/figure-requests",
            json=_payload(),
        )

    with _client(tmp_path) as restarted:
        listing = restarted.get(
            "/api/scientific-interpretation/language/figure-requests",
            params={"request_type": "DIAGRAM", "state": "PENDING_REVIEW"},
        )

    assert first.status_code == 201
    assert first.json()["created"] is True
    assert replay.status_code == 201
    assert replay.json()["created"] is False
    assert first.json()["item"]["request_id"] == replay.json()["item"]["request_id"]
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    item = listing.json()["items"][0]
    assert item["concept_id"] == CONCEPT_ID
    assert item["source_provenance"] == _payload()["source_provenance"]
    assert item["production_brief"] == (
        "Compare the labellum orientation before and after resupination."
    )
    assert item["review_required"] is True
    assert item["scientific_evidence"] is False
    assert item["figure_approval_authorized"] is False
    assert item["knowledge_graph_publication_authorized"] is False


def test_all_governed_figure_types_are_accepted(tmp_path):
    types = {
        "DIAGRAM",
        "SKETCH",
        "COLOR_ILLUSTRATION",
        "PHOTO_SET",
        "ANIMATION",
        "COMPARISON_PLATE",
        "DISSECTION",
    }
    with _client(tmp_path) as client:
        responses = [
            client.post(
                "/api/scientific-interpretation/language/figure-requests",
                json=_payload(request_type),
            )
            for request_type in types
        ]
    assert all(response.status_code == 201 for response in responses)
    assert len({response.json()["item"]["request_id"] for response in responses}) == 7


def test_unknown_figure_type_is_rejected_before_persistence(tmp_path):
    with _client(tmp_path) as client:
        response = client.post(
            "/api/scientific-interpretation/language/figure-requests",
            json=_payload("AI_GENERATED_SCIENCE"),
        )
    assert response.status_code == 422
    assert list(tmp_path.glob("*.json")) == []


def test_unreviewed_concept_fails_closed_before_persistence(tmp_path):
    with _client(tmp_path, FakeConceptService(review_state="PENDING")) as client:
        response = client.post(
            "/api/scientific-interpretation/language/figure-requests",
            json=_payload(),
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "FIGURE_REQUEST_CONCEPT_NOT_APPROVED"
    assert list(tmp_path.glob("*.json")) == []


def test_missing_concept_is_not_queued(tmp_path):
    payload = _payload()
    payload["concept_id"] = "00000000-0000-0000-0000-000000000000"
    with _client(tmp_path) as client:
        response = client.post(
            "/api/scientific-interpretation/language/figure-requests",
            json=payload,
        )
    assert response.status_code == 404
    assert list(tmp_path.glob("*.json")) == []


def test_corrupt_queue_fails_closed(tmp_path):
    (tmp_path / f"{'b' * 64}.json").write_text("not-json", encoding="utf-8")
    with _client(tmp_path) as client:
        response = client.get(
            "/api/scientific-interpretation/language/figure-requests"
        )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == (
        "FIGURE_REQUEST_PERSISTENCE_UNAVAILABLE"
    )


def test_invalid_request_identity_is_rejected_explicitly(tmp_path):
    with _client(tmp_path) as client:
        response = client.get(
            "/api/scientific-interpretation/language/figure-requests/not-a-digest"
        )
    assert response.status_code == 422


def test_filename_identity_mismatch_fails_closed(tmp_path):
    with _client(tmp_path) as client:
        created = client.post(
            "/api/scientific-interpretation/language/figure-requests",
            json=_payload(),
        ).json()["item"]
    original = tmp_path / f"{created['request_id']}.json"
    mismatched = tmp_path / f"{'c' * 64}.json"
    mismatched.write_text(json.dumps(created), encoding="utf-8")
    original.unlink()
    with _client(tmp_path) as client:
        response = client.get(
            "/api/scientific-interpretation/language/figure-requests"
        )
    assert response.status_code == 503
