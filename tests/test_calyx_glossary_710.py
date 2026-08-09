from __future__ import annotations

from uuid import uuid4

import pytest

from app.concepts.glossary import (
    CandidateState,
    FigureRequestType,
    GlossaryCandidateInput,
    GlossaryService,
)


class FakeRepository:
    def __init__(self) -> None:
        self.candidates: dict[str, dict] = {}
        self.figures: dict[str, dict] = {}

    def get_candidate(self, candidate_id):
        return self.candidates.get(candidate_id)

    def insert_candidate(self, row):
        self.candidates.setdefault(row["candidate_id"], dict(row))
        return self.candidates[row["candidate_id"]]

    def list_candidates(self, *, state, limit):
        rows = list(self.candidates.values())
        if state is not None:
            rows = [row for row in rows if row["resolution_state"] == state]
        return rows[:limit]

    def review_candidate(self, candidate_id, updates):
        row = self.candidates.get(candidate_id)
        if row is None:
            return None
        row.update(updates)
        return row

    def get_figure_request(self, request_id):
        return self.figures.get(request_id)

    def insert_figure_request(self, row):
        self.figures.setdefault(row["request_id"], dict(row))
        return self.figures[row["request_id"]]

    def list_figure_requests(self, *, concept_id, limit):
        rows = list(self.figures.values())
        if concept_id is not None:
            rows = [row for row in rows if str(row["concept_id"]) == str(concept_id)]
        return rows[:limit]


class FakeConcepts:
    def __init__(self, resolution="UNRESOLVED") -> None:
        self.resolution = resolution
        self.concept_id = uuid4()

    def search_concepts(self, query, *, language=None, limit=25):
        exact = [str(self.concept_id)] if self.resolution == "RESOLVED" else []
        return {"resolution": self.resolution, "exact_concept_ids": exact, "matches": []}

    def get_concept(self, concept_id):
        if concept_id != self.concept_id:
            raise LookupError("CONCEPT_NOT_FOUND")
        return {
            "concept_id": concept_id,
            "concept_uri": f"https://id.orchidcontinuum.org/concept/{concept_id}",
            "status": "ACTIVE",
            "review_state": "APPROVED",
        }

    def list_labels(self, concept_id):
        self.get_concept(concept_id)
        return [{"label": "Velamen", "label_type": "PREFERRED", "language": "en"}]

    def list_definitions(self, concept_id):
        self.get_concept(concept_id)
        return [{"text": "A multilayered root epidermis.", "definition_type": "SCIENTIFIC", "language": "en"}]


def _input(term="velamen"):
    return GlossaryCandidateInput(
        term=term,
        source_uri="doi:10.1000/example",
        source_revision_id="revision-7",
        source_checksum="a" * 64,
        evidence_span_id="span-42",
        language="en",
    )


def test_candidate_identity_is_deterministic_and_replay_idempotent():
    repo = FakeRepository()
    service = GlossaryService(repo, FakeConcepts())
    first = service.intake(_input())
    second = service.intake(_input())
    assert first["candidate_id"] == second["candidate_id"]
    assert len(repo.candidates) == 1
    assert first["source_uri"] == "doi:10.1000/example"
    assert first["source_revision_id"] == "revision-7"
    assert first["source_checksum"] == "a" * 64
    assert first["evidence_span_id"] == "span-42"
    assert first["automatic_concept_promotion"] is False
    assert first["knowledge_graph_publication_authorized"] is False


@pytest.mark.parametrize(
    ("resolution", "expected"),
    [
        ("UNRESOLVED", CandidateState.UNRESOLVED.value),
        ("CANDIDATES", CandidateState.CANDIDATES.value),
        ("AMBIGUOUS", CandidateState.AMBIGUOUS.value),
        ("RESOLVED", CandidateState.MATCHED_PENDING_REVIEW.value),
    ],
)
def test_resolution_never_auto_approves(resolution, expected):
    service = GlossaryService(FakeRepository(), FakeConcepts(resolution))
    candidate = service.intake(_input())
    assert candidate["resolution_state"] == expected
    assert candidate["resolution_state"] != CandidateState.REVIEWED_MATCH.value


def test_human_review_required_for_reviewed_match():
    repo = FakeRepository()
    concepts = FakeConcepts("RESOLVED")
    service = GlossaryService(repo, concepts)
    candidate = service.intake(_input())
    with pytest.raises(ValueError, match="CONCEPT_REQUIRED"):
        service.review_candidate(
            candidate["candidate_id"],
            state=CandidateState.REVIEWED_MATCH,
            actor="reviewer",
            rationale="exact reviewed match",
        )
    reviewed = service.review_candidate(
        candidate["candidate_id"],
        state=CandidateState.REVIEWED_MATCH,
        actor="reviewer",
        rationale="exact reviewed match",
        concept_id=concepts.concept_id,
    )
    assert reviewed["resolution_state"] == "REVIEWED_MATCH"
    assert reviewed["reviewed_concept_id"] == concepts.concept_id


def test_canonical_projection_reuses_concept_registry_content():
    concepts = FakeConcepts("RESOLVED")
    service = GlossaryService(FakeRepository(), concepts)
    entry = service.glossary_entry(concepts.concept_id)
    assert entry["canonical_source"] == "app.concepts"
    assert entry["labels"][0]["label"] == "Velamen"
    assert entry["definitions"][0]["text"].startswith("A multilayered")
    assert entry["generated_definition"] is False


def test_figure_request_is_deterministic_and_not_scientific_evidence():
    repo = FakeRepository()
    concepts = FakeConcepts("RESOLVED")
    service = GlossaryService(repo, concepts)
    first = service.create_figure_request(
        concept_id=concepts.concept_id,
        request_type=FigureRequestType.DIAGRAM,
        audience="general",
        purpose="Show velamen layers.",
    )
    second = service.create_figure_request(
        concept_id=concepts.concept_id,
        request_type=FigureRequestType.DIAGRAM,
        audience="general",
        purpose="Show velamen layers.",
    )
    assert first["request_id"] == second["request_id"]
    assert len(repo.figures) == 1
    assert first["figure_is_scientific_evidence"] is False
    assert first["automatic_generation_authorized"] is False
    assert first["automatic_publication_authorized"] is False
