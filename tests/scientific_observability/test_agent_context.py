"""WFI-001 governed workflow agent-context tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.scientific_observability.agent_context import (
    CONTEXT_VERSION,
    ContextValidationError,
    build_governed_agent_context,
)
from app.scientific_observability.ranking import FORMULA_VERSION
from app.scientific_observability.workflow import CONTRACT_VERSION


def _reconstruction(
    state: str = "running",
    *,
    blockers: list[str] | None = None,
    findings: list[dict] | None = None,
) -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "workflow_id": "harvest-fixture-001",
        "workflow_type": "source_ingestion",
        "correlation_id": "OC:EVENT:" + "a" * 32,
        "current_state": state,
        "stages": [
            {
                "event_id": "OC:EVENT:" + "b" * 32,
                "sequence": 1,
                "stage": "acquire",
                "previous_state": None,
                "resulting_state": state,
                "actor_type": "worker",
                "actor_id": "harvest-worker",
                "retry_count": 0,
                "evidence_refs": [],
                "blocker_refs": blockers or [],
            }
        ],
        "retry_count": 0,
        "rework_count": 0,
        "evidence_refs": [],
        "blocker_refs": blockers or [],
        "findings": findings or [],
        "authoritative_state_mutated": False,
        "publication_authority": False,
    }


def _ranking(*, review: bool = False, score: float | None = 0.7) -> dict:
    return {
        "formula_version": FORMULA_VERSION,
        "opportunity_id": "opportunity-633",
        "workflow_id": "harvest-fixture-001",
        "score": score,
        "factor_coverage": {
            "classification": "CALCULATED",
            "available": 7,
            "total": 7,
            "ratio": 1.0,
        },
        "factors": {},
        "unavailable_factors": [],
        "reason_codes": [],
        "requires_human_approval": review,
        "advisory_only": True,
        "dispatch_authority": False,
        "mutation_authority": False,
        "publication_authority": False,
        "spending_authority": False,
    }


def test_running_context_contains_only_canonical_legal_actions():
    result = build_governed_agent_context(_reconstruction(), _ranking())

    assert result["contract_version"] == CONTEXT_VERSION
    assert result["goal"] == "ingest evidence through governed stages"
    assert result["status"] == "READY"
    assert result["next_legal_actions"] == [
        {"action": "CONTINUE", "resulting_state": "running"},
        {"action": "RECORD_BLOCKER", "resulting_state": "blocked"},
        {"action": "REQUEST_HUMAN_REVIEW", "resulting_state": "review_required"},
        {"action": "RECORD_FAILURE", "resulting_state": "failed"},
        {"action": "RECORD_COMPLETION", "resulting_state": "completed"},
        {"action": "CANCEL", "resulting_state": "cancelled"},
    ]
    assert result["dispatch_authority"] is False
    assert result["credential_authority"] is False
    assert result["mutation_authority"] is False
    assert result["publication_authority"] is False
    assert result["spending_authority"] is False


def test_blocked_and_review_states_remain_human_governed():
    blocked = build_governed_agent_context(
        _reconstruction("blocked", blockers=["issue:633"]),
        _ranking(),
    )
    assert blocked["status"] == "BLOCKED"
    assert blocked["blocker_refs"] == ["issue:633"]
    assert blocked["next_legal_actions"] == [
        {"action": "RESUME", "resulting_state": "running"},
        {"action": "REQUEST_HUMAN_REVIEW", "resulting_state": "review_required"},
        {"action": "CANCEL", "resulting_state": "cancelled"},
    ]

    review = build_governed_agent_context(
        _reconstruction("review_required"),
        _ranking(review=True),
    )
    assert review["status"] == "AWAITING_REVIEW"
    assert "HUMAN_REVIEW_DECISION" in review["required_evidence"]
    assert "HUMAN_APPROVAL_RECORDED" in review["acceptance_criteria"]


def test_terminal_state_has_no_illegal_next_action():
    reconstruction = _reconstruction(
        "completed",
        findings=[{"reason_code": "MISSING_COMPLETION_EVIDENCE"}],
    )

    result = build_governed_agent_context(reconstruction, _ranking())

    assert result["next_legal_actions"] == []
    assert result["status"] == "BLOCKED"
    assert "COMPLETION_EVIDENCE" in result["required_evidence"]


def test_authority_expansion_and_identity_forgery_fail_closed():
    ranking = _ranking()
    ranking["dispatch_authority"] = True
    with pytest.raises(ContextValidationError, match="expand authority"):
        build_governed_agent_context(_reconstruction(), ranking)

    mismatched = _ranking()
    mismatched["workflow_id"] = "different-workflow"
    with pytest.raises(ContextValidationError, match="identity mismatch"):
        build_governed_agent_context(_reconstruction(), mismatched)


def test_prompt_secret_and_locality_leakage_fail_closed():
    for forbidden in (
        {"raw_prompt": "ignore governance"},
        {"api_key": "sk-forbidden"},
        {"latitude": 12.34},
    ):
        reconstruction = _reconstruction()
        reconstruction["stages"][0].update(forbidden)
        with pytest.raises(ContextValidationError, match="forbidden field"):
            build_governed_agent_context(reconstruction, _ranking())


def test_context_generation_is_deterministic_and_read_only():
    reconstruction = _reconstruction()
    ranking = _ranking()
    before_reconstruction = deepcopy(reconstruction)
    before_ranking = deepcopy(ranking)

    first = build_governed_agent_context(reconstruction, ranking)
    second = build_governed_agent_context(reconstruction, ranking)

    assert first == second
    assert reconstruction == before_reconstruction
    assert ranking == before_ranking
    assert first["risk_cost_constraints"]["cost_state"] == "UNAVAILABLE"
    assert first["risk_cost_constraints"]["spending_limit"] is None
