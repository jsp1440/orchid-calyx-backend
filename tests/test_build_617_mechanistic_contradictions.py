from __future__ import annotations

from app.brain.mechanistic_candidates import (
    MechanisticCandidateRequest,
    handoff_mechanistic_candidate,
)
from app.brain.mechanistic_contradictions import analyze_mechanistic_contradictions
from app.brain.mechanistic_publication_plan import (
    plan_mechanistic_candidate_publication,
)
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService


def components():
    repository = MemoryCandidateRepository()
    service = CandidateExtractionService(repository)
    return repository, service


def payload(
    relationship: str, *, tissue: str = "young leaf"
) -> MechanisticCandidateRequest:
    return MechanisticCandidateRequest.model_validate(
        {
            "reasoning_id": f"mechanism:light-auxin:{relationship}",
            "source": {
                "node_type": "environment",
                "label": "Directional blue light",
                "stable_key": "blue-light",
            },
            "relationship": relationship,
            "target": {
                "node_type": "physiology",
                "label": "Auxin redistribution",
                "stable_key": "auxin-redistribution",
            },
            "confidence": 0.8,
            "evidence_text": f"Directional blue light {relationship} auxin redistribution.",
            "source_object_type": "document_revision",
            "source_object_id": 201 if relationship == "promotes" else 301,
            "revision_id": 202 if relationship == "promotes" else 302,
            "extraction_run_id": 203 if relationship == "promotes" else 303,
            "source_anchors": [
                {
                    "anchor_id": 204 if relationship == "promotes" else 304,
                    "ordered_span": 0,
                    "page_number": 5,
                    "char_start": 0,
                    "char_end": 64,
                }
            ],
            "experimental_context": {"tissue": tissue, "stage": "expansion"},
            "quantitative_context": {"wavelength_nm": 450},
        }
    )


def approve(repository, candidate_id: int) -> None:
    for review_id, review in list(repository.reviews.items()):
        if review.get("candidate_id") == candidate_id and review.get("state") == "OPEN":
            repository.resolve_review(
                review_id,
                "APPROVE_CANDIDATE",
                "Evidence reviewed in context.",
                "qualified.science-reviewer",
            )


def test_opposite_polarity_same_scope_forms_publication_blocking_contradiction():
    repository, service = components()
    positive = handoff_mechanistic_candidate(payload("promotes"), (repository, service))
    negative = handoff_mechanistic_candidate(payload("inhibits"), (repository, service))

    report = analyze_mechanistic_contradictions((repository, service))

    assert report["contradiction_count"] == 1
    cluster = report["contradictions"][0]
    assert cluster["candidate_ids"] == sorted(
        [positive["candidate_ids"][0], negative["candidate_ids"][0]]
    )
    assert cluster["relationships"] == ["inhibits", "promotes"]
    assert cluster["publication_blocking"] is True
    assert cluster["resolved"] is False


def test_different_experimental_scope_does_not_create_false_contradiction():
    repository, service = components()
    handoff_mechanistic_candidate(
        payload("promotes", tissue="young leaf"), (repository, service)
    )
    handoff_mechanistic_candidate(
        payload("inhibits", tissue="root apex"), (repository, service)
    )

    report = analyze_mechanistic_contradictions((repository, service))

    assert report["contradiction_count"] == 0


def test_contradiction_blocks_otherwise_approved_publication_plan():
    repository, service = components()
    positive = handoff_mechanistic_candidate(payload("promotes"), (repository, service))
    negative = handoff_mechanistic_candidate(payload("inhibits"), (repository, service))
    positive_id = positive["candidate_ids"][0]
    negative_id = negative["candidate_ids"][0]
    approve(repository, positive_id)
    approve(repository, negative_id)

    plan = plan_mechanistic_candidate_publication(positive_id, (repository, service))

    assert plan["ready_for_controlled_publication_gate"] is False
    assert any(item.startswith("mechanistic_contradiction:") for item in plan["blockers"])
    assert plan["authorized"] is False
    assert plan["production_write_executed"] is False


def test_same_polarity_replicates_are_not_classified_as_contradiction():
    repository, service = components()
    handoff_mechanistic_candidate(payload("promotes"), (repository, service))
    second = payload("promotes").model_copy(
        update={
            "reasoning_id": "mechanism:light-auxin:promotes:replicate",
            "source_object_id": 401,
            "revision_id": 402,
            "extraction_run_id": 403,
            "source_anchors": [
                payload("promotes").source_anchors[0].model_copy(update={"anchor_id": 404})
            ],
        }
    )
    handoff_mechanistic_candidate(second, (repository, service))

    report = analyze_mechanistic_contradictions((repository, service))

    assert report["contradiction_count"] == 0
