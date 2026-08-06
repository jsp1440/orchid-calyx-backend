from __future__ import annotations

import pytest

from app.calyx_orchestrator.product_agents import (
    PRODUCT_ROLE_REGISTRY,
    PROHIBITED_PRODUCT_ACTIONS,
    ProductAgentRole,
    ProductResult,
    product_role_snapshot,
)
from app.calyx_orchestrator.product_program import (
    PRODUCT_DIRECTOR_JOB,
    PRODUCT_JOB_TEMPLATES,
    PRODUCT_PREREQUISITE_KEYS,
    build_product_program_fixture,
    product_mission_control_snapshot,
)


def test_all_phase_3_roles_are_registered() -> None:
    expected = {
        ProductAgentRole.CONSERVATORY_ENGINEER,
        ProductAgentRole.OASIS_ENGINEER,
        ProductAgentRole.RESEARCH_STATION_ENGINEER,
        ProductAgentRole.UNIVERSITY_ENGINEER,
        ProductAgentRole.MISSION_CONTROL_ENGINEER,
        ProductAgentRole.DOCUMENTATION_ENGINEER,
        ProductAgentRole.OPERATIONS_ENGINEER,
        ProductAgentRole.GRANT_FUNDING_AGENT,
        ProductAgentRole.PRODUCT_DIRECTOR,
    }
    assert set(PRODUCT_ROLE_REGISTRY) == expected
    assert len(product_role_snapshot()) == 9


def test_product_result_requires_role_evidence() -> None:
    result = ProductResult(role=ProductAgentRole.CONSERVATORY_ENGINEER, evidence={})
    with pytest.raises(ValueError, match="REQUIRED_PRODUCT_EVIDENCE_MISSING"):
        result.validate()


def test_product_result_rejects_prohibited_action() -> None:
    evidence = {
        "collection_contract": {},
        "qr_workflow": {},
        "identity_rules": {},
        "tests": [],
        "human_action": "Review the draft PR.",
    }
    result = ProductResult(
        role=ProductAgentRole.CONSERVATORY_ENGINEER,
        evidence=evidence,
        requested_action="production_deployment",
    )
    with pytest.raises(PermissionError, match="PRODUCT_ACTION_PROHIBITED"):
        result.validate()


def test_product_result_accepts_governed_delivery() -> None:
    evidence = {
        "document_index": ["README.md"],
        "runbook_coverage": {"covered": True},
        "decision_log": ["ADR-001"],
        "tests": ["test_docs"],
        "human_action": "Review documentation before merge.",
    }
    ProductResult(
        role=ProductAgentRole.DOCUMENTATION_ENGINEER,
        evidence=evidence,
        deployment_state="ready_for_owner_review",
        requested_action="Review documentation before merge.",
    ).validate()


def test_product_program_has_eight_domain_jobs_and_director() -> None:
    fixture = build_product_program_fixture()
    assert len(PRODUCT_JOB_TEMPLATES) == 8
    assert len(fixture["jobs"]) == 9
    assert fixture["max_active_jobs"] == 6
    assert PRODUCT_DIRECTOR_JOB.depends_on == PRODUCT_PREREQUISITE_KEYS


def test_product_director_depends_on_every_domain_job() -> None:
    fixture = build_product_program_fixture()
    edges = {(edge["upstream"], edge["downstream"]) for edge in fixture["dependencies"]}
    assert edges == {(key, PRODUCT_DIRECTOR_JOB.job_key) for key in PRODUCT_PREREQUISITE_KEYS}


def test_product_program_safety_fails_closed() -> None:
    fixture = build_product_program_fixture()
    assert all(value is False for value in fixture["safety"].values())
    assert {
        "automatic_merge",
        "production_deployment",
        "submit_grant",
        "make_binding_commitment",
    }.issubset(PROHIBITED_PRODUCT_ACTIONS)


def test_product_mission_control_snapshot_is_complete() -> None:
    snapshot = product_mission_control_snapshot()
    assert snapshot["phase"] == 3
    assert snapshot["role_count"] == 9
    assert len(snapshot["job_templates"]) == 9
    assert snapshot["program"]["release_rule"]["job_key"] == "product_director_report"
    assert snapshot["human_actions"]
