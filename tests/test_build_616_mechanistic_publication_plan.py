from __future__ import annotations

from app.brain.mechanistic_candidates import (
    MechanisticCandidateRequest,
    handoff_mechanistic_candidate,
)
from app.brain.mechanistic_publication_plan import (
    plan_mechanistic_candidate_publication,
)
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService


def components():
    repository = MemoryCandidateRepository()
    service = CandidateExtractionService(repository)
    return repository, service


def request() -> MechanisticCandidateRequest:
    return MechanisticCandidateRequest.model_validate(
        {
            "reasoning_id": "mechanism:phototropism:001",
            "source": {
                "node_type": "environment",
                "label": "Directional blue light",
                "stable_key": "blue-light",
            },
            "relationship": "promotes",
            "target": {
                "node_type": "physiology",
                "label": "Auxin redistribution",
                "stable_key": "auxin-redistribution",
            },
            "confidence": 0.86,
            "evidence_text": "Directional blue light promoted auxin redistribution in young tissue.",
            "source_object_type": "document_revision",
            "source_object_id": 101,
            "revision_id": 102,
            "extraction_run_id": 103,
            "source_anchors": [
                {
                    "anchor_id": 104,
                    "ordered_span": 0,
                    "page_number": 4,
                    "char_start": 10,
                    "char_end": 79,
                    "locator": {"confidence": 0.99},
                }
            ],
            "experimental_context": {"tissue": "young leaf"},
            "quantitative_context": {"wavelength_nm": 450},
            "provenance": {"doi": "10.0000/example"},
        }
    )


def create_candidate(repository, service) -> int:
    result = handoff_mechanistic_candidate(request(), (repository, service))
    return result["candidate_ids"][0]


def approve_all_candidate_reviews(repository, candidate_id: int) -> None:
    for review_id, review in list(repository.reviews.items()):
        if review.get("candidate_id") == candidate_id and review.get("state") == "OPEN":
            repository.resolve_review(
                review_id,
                "APPROVE_CANDIDATE",
                "Mechanistic claim and exact evidence reviewed.",
                "qualified.science-reviewer",
            )


def test_unreviewed_candidate_is_blocked_and_never_authorized():
    repository, service = components()
    candidate_id = create_candidate(repository, service)
    plan = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    assert plan["ready_for_controlled_publication_gate"] is False
    assert plan["authorized"] is False
    assert plan["commit_capability"] is False
    assert plan["production_write_executed"] is False
    assert "scientific_review_not_approved" in plan["blockers"]
    assert any(item.startswith("open_review:") for item in plan["blockers"])


def test_approved_candidate_produces_deterministic_three_operation_plan():
    repository, service = components()
    candidate_id = create_candidate(repository, service)
    approve_all_candidate_reviews(repository, candidate_id)
    first = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    second = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    assert first["ready_for_controlled_publication_gate"] is True
    assert first["blockers"] == []
    assert first["validation"]["healthy"] is True
    assert first["plan_id"] == second["plan_id"]
    assert [item["operation"] for item in first["operations"]] == [
        "UPSERT_NODE",
        "UPSERT_NODE",
        "UPSERT_EDGE",
    ]
    assert first["authorized"] is False
    assert first["canonical_graph_mutated"] is False


def test_open_conflict_blocks_plan_even_after_review_approval():
    repository, service = components()
    candidate_id = create_candidate(repository, service)
    approve_all_candidate_reviews(repository, candidate_id)
    repository.conflicts[900] = {
        "conflict_id": 900,
        "candidate_ids": [candidate_id, 999],
        "state": "OPEN",
    }
    plan = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    assert plan["ready_for_controlled_publication_gate"] is False
    assert "open_conflict:900" in plan["blockers"]


def test_missing_evidence_blocks_publication_plan():
    repository, service = components()
    candidate_id = create_candidate(repository, service)
    approve_all_candidate_reviews(repository, candidate_id)
    repository.evidence_links = []
    plan = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    assert plan["ready_for_controlled_publication_gate"] is False
    assert "exact_evidence_required" in plan["blockers"]


def test_plan_preserves_context_and_uses_truthful_preview_provenance():
    repository, service = components()
    candidate_id = create_candidate(repository, service)
    approve_all_candidate_reviews(repository, candidate_id)
    plan = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    source = plan["operations"][0]["payload"]
    target = plan["operations"][1]["payload"]
    edge = plan["operations"][2]["payload"]
    assert source["provenance"]["source_table"] == "synthetic.mechanistic_publication_plan"
    assert target["provenance"]["source_table"] == "synthetic.mechanistic_publication_plan"
    assert edge["provenance"]["source_table"] == "oc_candidate_knowledge.candidates"
    assert edge["provenance"]["source_pk"] == str(candidate_id)
    assert edge["edge_type"] == "promotes"
    assert edge["payload"]["polarity"] == 1
    assert edge["payload"]["experimental_context"]["tissue"] == "young leaf"
    assert edge["payload"]["quantitative_context"]["wavelength_nm"] == 450
    assert plan["requires_explicit_publication_authorization"] is True
