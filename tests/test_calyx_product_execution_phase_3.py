from __future__ import annotations

import pytest

from app.calyx_orchestrator.product_agents import ProductAgentRole
from app.calyx_orchestrator.product_execution import (
    product_program_specs,
    validate_product_payload,
)
from app.calyx_orchestrator.product_program import (
    PRODUCT_DIRECTOR_JOB,
    PRODUCT_PREREQUISITE_KEYS,
)


def test_product_program_specs_are_persistable() -> None:
    jobs, dependencies = product_program_specs()
    assert len(jobs) == 9
    assert len(dependencies) == 8
    assert {job.job_key for job in jobs} == {*PRODUCT_PREREQUISITE_KEYS, PRODUCT_DIRECTOR_JOB.job_key}
    assert all(job.repository == "jsp1440/orchid-calyx-backend" for job in jobs)
    assert all(job.branch and job.branch.startswith("product/") for job in jobs)
    assert all(job.mutating is False for job in jobs)


def test_validate_product_payload_accepts_governed_result() -> None:
    evidence = {
        "collection_contract": {"version": 1},
        "qr_workflow": {"scan_to_record": True},
        "identity_rules": {"accession_unique": True},
        "tests": ["qr_round_trip"],
        "human_action": "Review the draft PR before merge.",
        "dependencies": [],
        "blockers": [],
        "deployment_state": "ready_for_owner_review",
        "requested_action": "Review the draft PR before merge.",
    }
    result = validate_product_payload(
        role_key=ProductAgentRole.CONSERVATORY_ENGINEER.value,
        evidence=evidence,
    )
    assert result.role is ProductAgentRole.CONSERVATORY_ENGINEER
    assert result.deployment_state == "ready_for_owner_review"


def test_validate_product_payload_rejects_unknown_role() -> None:
    with pytest.raises(ValueError, match="PRODUCT_ROLE_REQUIRED"):
        validate_product_payload(role_key="unknown", evidence={})


def test_validate_product_payload_rejects_prohibited_action() -> None:
    evidence = {
        "opportunity_identity": "grant-1",
        "eligibility": True,
        "deadline": "2026-09-01",
        "draft_artifact": "draft.md",
        "human_action": "Review and decide whether to submit.",
        "requested_action": "submit_grant",
    }
    with pytest.raises(PermissionError, match="PRODUCT_ACTION_PROHIBITED"):
        validate_product_payload(
            role_key=ProductAgentRole.GRANT_FUNDING_AGENT.value,
            evidence=evidence,
        )


def test_validate_product_payload_rejects_invalid_collection_types() -> None:
    evidence = {
        "document_index": [],
        "runbook_coverage": {},
        "decision_log": [],
        "tests": [],
        "human_action": "Review documentation.",
        "dependencies": "invalid",
    }
    with pytest.raises(TypeError, match="PRODUCT_DEPENDENCIES_INVALID"):
        validate_product_payload(
            role_key=ProductAgentRole.DOCUMENTATION_ENGINEER.value,
            evidence=evidence,
        )
