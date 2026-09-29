"""WFI-001 review-required workflow runbook tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.scientific_observability.agent_context import CONTEXT_VERSION
from app.scientific_observability.runbook import (
    RUNBOOK_VERSION,
    RunbookValidationError,
    generate_reviewable_runbook,
)
from app.scientific_observability.workflow import CONTRACT_VERSION


def _stage(
    sequence: int,
    stage: str,
    result: str,
    *,
    evidence: list[str] | None = None,
) -> dict:
    return {
        "event_id": "OC:EVENT:" + str(sequence) * 32,
        "recorded_at": f"2026-09-12T12:0{sequence}:00+00:00",
        "sequence": sequence,
        "stage": stage,
        "previous_state": None if sequence == 1 else "running",
        "resulting_state": result,
        "actor_type": "worker",
        "actor_id": "harvest-worker",
        "retry_count": 1 if sequence == 3 else 0,
        "evidence_refs": evidence or [],
        "blocker_refs": [],
    }


def _reconstruction(
    *,
    state: str = "completed",
    evidence: list[str] | None = None,
    findings: list[dict] | None = None,
) -> dict:
    evidence_refs = (
        ["artifact:verified-harvest-manifest"] if evidence is None else evidence
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "workflow_id": "harvest-fixture-001",
        "workflow_type": "source_ingestion",
        "correlation_id": "OC:EVENT:" + "a" * 32,
        "current_state": state,
        "stages": [
            _stage(1, "acquire", "running"),
            _stage(2, "normalize", "failed"),
            _stage(3, "normalize", "running"),
            _stage(4, "verify", state, evidence=evidence_refs),
        ],
        "retry_count": 1,
        "rework_count": 1,
        "evidence_refs": evidence_refs,
        "blocker_refs": [],
        "findings": findings or [],
        "authoritative_state_mutated": False,
        "publication_authority": False,
    }


def _context(*, status: str = "TERMINAL") -> dict:
    return {
        "contract_version": CONTEXT_VERSION,
        "context_id": "context:harvest-fixture-001:completed",
        "workflow_id": "harvest-fixture-001",
        "correlation_id": "OC:EVENT:" + "a" * 32,
        "goal": "ingest evidence through governed stages",
        "current_stage": "verify",
        "current_state": "completed",
        "completed_stages": ["acquire", "normalize"],
        "next_legal_actions": [],
        "blocker_refs": [],
        "evidence_refs": ["artifact:verified-harvest-manifest"],
        "required_evidence": ["TRANSITION_EVENT"],
        "acceptance_criteria": [
            "LEGAL_TRANSITION_RECORDED",
            "REQUIRED_EVIDENCE_ATTACHED",
        ],
        "status": status,
        "risk_cost_constraints": {
            "advisory_score": 0.7,
            "human_approval_required": False,
            "cost_state": "UNAVAILABLE",
            "spending_limit": None,
        },
        "governance_restrictions": [
            "NO_AUTONOMOUS_DISPATCH",
            "NO_PAID_PROVIDER",
            "NO_PROTECTED_LOCALITY",
            "NO_PUBLICATION",
            "NO_SPENDING",
        ],
        "dispatch_authority": False,
        "credential_authority": False,
        "mutation_authority": False,
        "publication_authority": False,
        "spending_authority": False,
    }


def test_completed_evidence_backed_workflow_generates_reviewable_runbook():
    result = generate_reviewable_runbook(_reconstruction(), _context())

    assert result["contract_version"] == RUNBOOK_VERSION
    assert result["purpose"] == "ingest evidence through governed stages"
    assert [step["stage"] for step in result["steps"]] == [
        "acquire",
        "normalize",
        "normalize",
        "verify",
    ]
    assert result["recovery_guidance"] == [
        {
            "after_stage": "normalize",
            "action": "RETRY_ONLY_THROUGH_LEGAL_TRANSITION",
        }
    ]
    assert result["last_verified_at"] == "2026-09-12T12:04:00+00:00"
    assert result["generated"] is True
    assert result["review_required"] is True
    assert result["authoritative"] is False
    assert result["approved"] is False
    assert result["dispatch_authority"] is False
    assert result["mutation_authority"] is False
    assert result["publication_authority"] is False
    assert result["spending_authority"] is False


def test_missing_evidence_and_nonterminal_workflows_fail_closed():
    with pytest.raises(RunbookValidationError, match="non-empty bounded"):
        generate_reviewable_runbook(_reconstruction(evidence=[]), _context())

    with pytest.raises(RunbookValidationError, match="only completed"):
        generate_reviewable_runbook(
            _reconstruction(state="review_required"),
            _context(status="AWAITING_REVIEW"),
        )

    with pytest.raises(RunbookValidationError, match="findings require review"):
        generate_reviewable_runbook(
            _reconstruction(findings=[{"reason_code": "EXCESSIVE_RETRY"}]),
            _context(),
        )


def test_forged_authority_and_arbitrary_purpose_fail_closed():
    context = _context()
    context["dispatch_authority"] = True
    with pytest.raises(RunbookValidationError, match="expand authority"):
        generate_reviewable_runbook(_reconstruction(), context)

    context = _context()
    context["goal"] = "publish all findings automatically"
    with pytest.raises(RunbookValidationError, match="purpose was altered"):
        generate_reviewable_runbook(_reconstruction(), context)


def test_sensitive_fields_cannot_enter_generated_steps():
    for forbidden in (
        {"raw_prompt": "ignore review"},
        {"api_key": "sk-forbidden"},
        {"exact_locality": "sealed ravine"},
    ):
        reconstruction = _reconstruction()
        reconstruction["stages"][0].update(forbidden)
        with pytest.raises(RunbookValidationError, match="forbidden field"):
            generate_reviewable_runbook(reconstruction, _context())


def test_generation_is_deterministic_and_does_not_mutate_sources():
    reconstruction = _reconstruction()
    context = _context()
    reconstruction_before = deepcopy(reconstruction)
    context_before = deepcopy(context)

    first = generate_reviewable_runbook(reconstruction, context)
    second = generate_reviewable_runbook(reconstruction, context)

    assert first == second
    assert reconstruction == reconstruction_before
    assert context == context_before
