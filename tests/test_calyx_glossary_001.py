from uuid import UUID, uuid4

import pytest

from app.concepts.glossary import FigureRequestType, ScientificLanguageService


class FakeConceptService:
    def __init__(self, resolution: str = "UNRESOLVED") -> None:
        self.resolution = resolution
        self.concept_id = uuid4()

    def search_concepts(self, query, *, language=None, limit=25):
        exact = [str(self.concept_id)] if self.resolution == "RESOLVED" else []
        return {
            "query": query,
            "normalized_query": query.casefold(),
            "resolution": self.resolution,
            "exact_concept_ids": exact,
            "matches": [],
        }

    def get_concept(self, identifier):
        return {
            "concept_id": self.concept_id if not isinstance(identifier, UUID) else identifier,
            "concept_uri": f"https://id.orchidcontinuum.org/concept/{self.concept_id}",
            "status": "ACTIVE",
            "review_state": "APPROVED",
        }

    def list_labels(self, identifier):
        return [
            {
                "concept_id": self.concept_id,
                "label_type": "PREFERRED",
                "label": "velamen",
                "language": "en",
            },
            {
                "concept_id": self.concept_id,
                "label_type": "ALTERNATE",
                "label": "velamen radicum",
                "language": "en",
            },
        ]

    def list_definitions(self, identifier):
        return [
            {
                "concept_id": self.concept_id,
                "definition_type": "GLOSSARY",
                "text": "A multilayered root epidermis found in many epiphytic orchids.",
                "language": "en",
            }
        ]


class FakeGlossaryRepository:
    def __init__(self):
        self.candidates = {}
        self.figures = {}

    def upsert_candidate(self, data):
        existing = self.candidates.get(data["fingerprint"])
        if existing is None:
            existing = dict(data)
            self.candidates[data["fingerprint"]] = existing
        return existing

    def list_candidates(self, *, resolution_state=None, limit=100):
        rows = list(self.candidates.values())
        if resolution_state:
            rows = [row for row in rows if row["resolution_state"] == resolution_state]
        return rows[:limit]

    def upsert_figure_request(self, data):
        existing = self.figures.get(data["fingerprint"])
        if existing is None:
            existing = {
                **dict(data),
                "status": "REQUESTED",
                "review_required": True,
                "scientific_evidence": False,
            }
            self.figures[data["fingerprint"]] = existing
        return existing

    def list_figure_requests(self, *, concept_id=None, status=None, limit=100):
        rows = list(self.figures.values())
        if concept_id:
            rows = [row for row in rows if row["concept_id"] == concept_id]
        if status:
            rows = [row for row in rows if row["status"] == status]
        return rows[:limit]


def service(resolution="UNRESOLVED"):
    concepts = FakeConceptService(resolution)
    repository = FakeGlossaryRepository()
    return ScientificLanguageService(concept_service=concepts, repository=repository), concepts, repository


def test_candidate_identity_is_deterministic_and_replay_is_idempotent():
    svc, _, repo = service("UNRESOLVED")
    payload = {
        "term": "Velamen",
        "source_kind": "LITERATURE_EVIDENCE",
        "source_hash": "a" * 64,
        "source_locator": {"paper_id": "paper-1", "evidence_id": "ev-1"},
        "language": "en",
        "char_start": 10,
        "char_end": 17,
    }
    first = svc.intake_candidate(**payload)
    second = svc.intake_candidate(**payload)
    assert first["candidate_id"] == second["candidate_id"]
    assert len(repo.candidates) == 1
    assert first["resolution_state"] == "UNRESOLVED"
    assert first["provenance"]["automatic_canonical_promotion"] is False


def test_exact_match_is_review_required_not_auto_promoted():
    svc, concepts, _ = service("RESOLVED")
    result = svc.intake_candidate(
        term="velamen",
        source_kind="LITERATURE_EVIDENCE",
        source_hash="b" * 64,
        source_locator={"paper_id": "paper-2"},
    )
    assert result["resolution_state"] == "MATCHED_PENDING_REVIEW"
    assert result["matched_concept_id"] == concepts.concept_id
    assert result["review_state"] == "PENDING"


@pytest.mark.parametrize(
    ("resolution", "expected"),
    [("AMBIGUOUS", "AMBIGUOUS"), ("CANDIDATES", "CANDIDATES")],
)
def test_non_exact_resolution_is_preserved(resolution, expected):
    svc, _, _ = service(resolution)
    result = svc.intake_candidate(
        term="lip",
        source_kind="LITERATURE_EVIDENCE",
        source_hash="c" * 64,
        source_locator={"paper_id": "paper-3"},
    )
    assert result["resolution_state"] == expected
    assert result["matched_concept_id"] is None


def test_incomplete_source_span_fails_closed():
    svc, _, _ = service()
    with pytest.raises(ValueError, match="GLOSSARY_SOURCE_SPAN_INCOMPLETE"):
        svc.intake_candidate(
            term="velamen",
            source_kind="LITERATURE_EVIDENCE",
            source_hash="d" * 64,
            source_locator={"paper_id": "paper-4"},
            char_start=5,
        )


def test_glossary_projection_reuses_canonical_concept_lexical_records():
    svc, concepts, _ = service()
    entry = svc.glossary_entry(concepts.concept_id)
    assert entry["canonical_source"] == "oc_concepts"
    assert entry["preferred_labels"][0]["label"] == "velamen"
    assert entry["definitions"][0]["definition_type"] == "GLOSSARY"
    assert entry["pronunciation"] is None


def test_figure_request_is_deterministic_and_never_scientific_evidence():
    svc, concepts, repo = service()
    payload = {
        "concept_id": concepts.concept_id,
        "request_type": FigureRequestType.DIAGRAM,
        "title": "Velamen cross-section",
        "generation_prompt": "Diagram a transverse orchid root section showing velamen layers.",
        "caption": "Simplified teaching diagram; not primary evidence.",
        "priority": 80,
    }
    first = svc.request_figure(**payload)
    second = svc.request_figure(**payload)
    assert first["request_id"] == second["request_id"]
    assert len(repo.figures) == 1
    assert first["review_required"] is True
    assert first["scientific_evidence"] is False
    assert first["provenance"]["human_review_required"] is True
