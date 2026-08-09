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


def components(repository=None):
    repository = repository or MemoryCandidateRepository()
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
    assert plan["operations"] == []
    assert "scientific_review_not_approved" in plan["blockers"]
    assert "scientific_approval_record_required" in plan["blockers"]
    assert any(item.startswith("open_review:") for item in plan["blockers"])


def test_approved_candidate_produces_review_bound_deterministic_plan():
    repository, service = components()
    candidate_id = create_candidate(repository, service)
    approve_all_candidate_reviews(repository, candidate_id)
    first = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    second = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    assert first["contract"] == "calyx-mechanistic-publication-plan-v2"
    assert first["ready_for_controlled_publication_gate"] is True
    assert first["blockers"] == []
    assert first["validation"]["healthy"] is True
    assert first["plan_id"] == second["plan_id"]
    assert first["approval"]["decision"] == "APPROVE_CANDIDATE"
    assert first["approval"]["actor"] == "qualified.science-reviewer"
    assert len(first["approval"]["reviewed_content_digest"]) == 64
    assert [item["operation_type"] for item in first["operations"]] == [
        "UPSERT_NODE",
        "UPSERT_NODE",
        "UPSERT_EDGE",
    ]
    assert first["authorized"] is False
    assert first["canonical_graph_mutated"] is False
    assert first["publication_adapter_available"] is False
    assert "No canonical adapter" in first["operator_action"]


def test_plan_id_changes_when_exact_approval_record_changes():
    repository, service = components()
    candidate_id = create_candidate(repository, service)
    approve_all_candidate_reviews(repository, candidate_id)
    first = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    approval_review = repository.reviews[first["approval"]["review_id"]]
    approval_review["actor"] = "second.qualified.reviewer"
    approval_review["rationale"] = "Independent repeat review of the same evidence."
    approval_review["resolved_at"] = "2026-08-09T17:00:00+00:00"
    second = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    assert second["approval"]["actor"] == "second.qualified.reviewer"
    assert second["plan_id"] != first["plan_id"]


def test_repository_refresh_is_used_before_reading_publication_state():
    class RefreshingRepository(MemoryCandidateRepository):
        def __init__(self):
            super().__init__()
            self.refresh_calls = 0

        def refresh(self):
            self.refresh_calls += 1
            return self

    repository, service = components(RefreshingRepository())
    candidate_id = create_candidate(repository, service)
    plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    assert repository.refresh_calls == 1


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
    assert plan["operations"] == []
    assert "open_conflict:900" in plan["blockers"]


def test_resolve_conflict_closes_exact_canonical_conflict():
    repository, service = components()
    candidate_id = create_candidate(repository, service)
    conflict_id = 900
    repository.conflicts[conflict_id] = {
        "conflict_id": conflict_id,
        "candidate_ids": [candidate_id, 999],
        "state": "OPEN",
    }
    run_id = repository.candidates[0]["candidate_run_id"]
    review = repository.open_review(
        run_id,
        candidate_id,
        "CONFLICTING_CANDIDATES",
        "HIGH",
        {"conflict_id": conflict_id},
    )
    repository.resolve_review(
        review["review_id"],
        "RESOLVE_CONFLICT",
        "Evidence scopes are distinct; conflict closed without approval.",
        "qualified.science-reviewer",
    )
    assert repository.conflicts[conflict_id]["state"] == "RESOLVED"
    assert (
        repository.conflicts[conflict_id]["resolution_review_id"] == review["review_id"]
    )
    assert repository.candidates[0]["review_state"] == "CHANGES_REQUESTED"


def test_missing_evidence_blocks_publication_plan():
    repository, service = components()
    candidate_id = create_candidate(repository, service)
    approve_all_candidate_reviews(repository, candidate_id)
    repository.evidence_links = []
    plan = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    assert plan["ready_for_controlled_publication_gate"] is False
    assert plan["operations"] == []
    assert "exact_evidence_required" in plan["blockers"]


def test_plan_uses_canonical_endpoint_resolution_and_candidate_provenance():
    repository, service = components()
    candidate_id = create_candidate(repository, service)
    approve_all_candidate_reviews(repository, candidate_id)
    plan = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    edge = plan["operations"][2]["payload"]
    source = plan["operations"][0]["payload"]
    target = plan["operations"][1]["payload"]
    assert edge["edge_type"] == "promotes"
    assert edge["endpoint_resolution"] == "canonical_key"
    assert edge["from_canonical_key"] == "environment:blue-light"
    assert edge["to_canonical_key"] == "physiology:auxin-redistribution"
    assert "from_node_id" not in edge and "to_node_id" not in edge
    assert edge["payload"]["polarity"] == 1
    assert edge["payload"]["experimental_context"]["tissue"] == "young leaf"
    assert edge["payload"]["quantitative_context"]["wavelength_nm"] == 450
    assert source["candidate_provenance"]["source_pk"] == str(candidate_id)
    assert target["candidate_provenance"]["source_pk"] == str(candidate_id)
    assert plan["requires_explicit_publication_authorization"] is True
