from fastapi.testclient import TestClient

from app.concepts.dependencies import get_concept_service
from app.main import app
from app.security import verify_owner_or_api_key

CONCEPT_ID = "2b16acee-3af8-4f87-8acd-e4f7c8f5db1b"


class FakeConceptService:
    def __init__(self, *, status="ACTIVE", review_state="APPROVED"):
        self.status = status
        self.review_state = review_state

    def get_concept(self, identifier):
        if identifier == "missing":
            raise LookupError("CONCEPT_NOT_FOUND")
        return {
            "concept_id": CONCEPT_ID,
            "concept_uri": f"https://id.orchidcontinuum.org/concept/{CONCEPT_ID}",
            "status": self.status,
            "review_state": self.review_state,
        }

    def list_labels(self, identifier):
        return [
            {
                "label_id": "2",
                "label_type": "ALTERNATE",
                "label": "upside-down flower",
                "normalized_label": "upside-down flower",
                "language": "en",
                "review_state": "APPROVED",
            },
            {
                "label_id": "1",
                "label_type": "PREFERRED",
                "label": "resupination",
                "normalized_label": "resupination",
                "language": "en",
                "review_state": "APPROVED",
            },
            {
                "label_id": "3",
                "label_type": "HIDDEN",
                "label": "unreviewed wording",
                "normalized_label": "unreviewed wording",
                "language": "en",
                "review_state": "PENDING",
            },
        ]

    def list_definitions(self, identifier):
        return [
            {
                "definition_id": "2",
                "definition_type": "LEARNER",
                "text": "A flower turning during development.",
                "language": "en",
                "review_state": "APPROVED",
            },
            {
                "definition_id": "1",
                "definition_type": "NORMATIVE_SCIENTIFIC",
                "text": "Rotation of an organ relative to its initial orientation.",
                "language": "en",
                "review_state": "APPROVED",
            },
            {
                "definition_id": "3",
                "definition_type": "PLAIN_LANGUAGE",
                "text": "Unreviewed draft.",
                "language": "en",
                "review_state": "PENDING",
            },
        ]


def _client(service):
    app.dependency_overrides[get_concept_service] = lambda: service
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "test-owner"
    }
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.pop(get_concept_service, None)
    app.dependency_overrides.pop(verify_owner_or_api_key, None)


def test_projection_returns_only_reviewed_registry_content():
    response = _client(FakeConceptService()).get(
        f"/api/scientific-interpretation/language/glossary/{CONCEPT_ID}",
        params={"language": "en"},
    )

    assert response.status_code == 200
    body = response.json()
    assert [row["label"] for row in body["labels"]] == [
        "resupination",
        "upside-down flower",
    ]
    assert set(body["definitions_by_audience"]) == {
        "LEARNER",
        "NORMATIVE_SCIENTIFIC",
    }
    assert body["source"] == "app.concepts"
    assert body["read_only"] is True
    assert body["reviewed_content_only"] is True
    assert body["definition_invention_authorized"] is False
    assert body["canonical_mutation_authorized"] is False
    assert body["knowledge_graph_publication_authorized"] is False


def test_projection_fails_closed_for_unreviewed_or_inactive_concept():
    for service in (
        FakeConceptService(status="DRAFT"),
        FakeConceptService(review_state="PENDING"),
    ):
        response = _client(service).get(
            f"/api/scientific-interpretation/language/glossary/{CONCEPT_ID}"
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == (
            "CANONICAL_GLOSSARY_CONCEPT_NOT_APPROVED"
        )


def test_projection_returns_explicit_not_found():
    response = _client(FakeConceptService()).get(
        "/api/scientific-interpretation/language/glossary/missing"
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "CONCEPT_NOT_FOUND"
