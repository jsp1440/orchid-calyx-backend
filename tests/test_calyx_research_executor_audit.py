"""Tests for Calyx research executor audit (Approved Task Priority 12)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.calyx_research_executor_audit import (
    EXECUTOR_AUDIT_CRITERIA,
    ExecutorAuditStatus,
    get_calyx_research_executor_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_calyx_research_executor_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "calyx-research-executor-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(EXECUTOR_AUDIT_CRITERIA) >= 12


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(EXECUTOR_AUDIT_CRITERIA)


# READY
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(ExecutorAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(ExecutorAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(ExecutorAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(ExecutorAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 12


# GAP
def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(ExecutorAuditStatus.GAP):
        assert c.gap_description


def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


# BLOCKED
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(ExecutorAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_no_api_cited_in_blocked():
    blocked = _AUDIT.by_status(ExecutorAuditStatus.BLOCKED)
    assert any("NO-API" in (c.blocker_reason or "") for c in blocked)


# OWNER_GATED
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(ExecutorAuditStatus.OWNER_GATED):
        assert c.next_action


def test_production_promotion_is_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExecutorAuditStatus.OWNER_GATED)}
    assert "security_production_promotion_owner_gated" in ids


# Area coverage
EXPECTED_AREAS = {"state_machine", "governance", "literature", "registry", "dry_run", "security"}


def test_all_areas_covered():
    actual = {c.area for c in EXECUTOR_AUDIT_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from executor audit"


def test_state_machine_area_has_criteria():
    assert len(get_criteria_by_area("state_machine")) >= 3


def test_governance_area_has_criteria():
    assert len(get_criteria_by_area("governance")) >= 2


def test_literature_area_has_criteria():
    assert len(get_criteria_by_area("literature")) >= 2


def test_registry_area_has_criteria():
    assert len(get_criteria_by_area("registry")) >= 2


def test_dry_run_area_has_criteria():
    assert len(get_criteria_by_area("dry_run")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


# Key criteria
def test_state_machine_valid_transitions_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExecutorAuditStatus.READY)}
    assert "state_machine_valid_transitions" in ids


def test_governance_authority_constants_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExecutorAuditStatus.READY)}
    assert "governance_authority_constants" in ids


def test_governance_review_required_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExecutorAuditStatus.READY)}
    assert "governance_review_required" in ids


def test_dry_run_prohibited_capabilities_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExecutorAuditStatus.READY)}
    assert "dry_run_prohibited_capabilities" in ids


def test_no_kg_mutation_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExecutorAuditStatus.READY)}
    assert "security_no_kg_mutation" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == ExecutorAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(ExecutorAuditStatus.READY):
        assert c.status == ExecutorAuditStatus.READY


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["area"]
        assert action["title"]
        assert action["status"]
        assert action["next_action"]


def test_get_next_actions_non_empty():
    assert get_next_actions()


# Serialization
def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "calyx-research-executor-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output, f"Credential key {key!r} found in output"


def test_json_contains_no_coordinate_fields():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"latitude"', '"longitude"', '"lat":', '"lon":', '"lng":']:
        assert key not in output


# Structure
def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in EXECUTOR_AUDIT_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {ExecutorAuditStatus.READY, ExecutorAuditStatus.GAP,
             ExecutorAuditStatus.BLOCKED, ExecutorAuditStatus.OWNER_GATED}
    for c in EXECUTOR_AUDIT_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in EXECUTOR_AUDIT_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in EXECUTOR_AUDIT_CRITERIA:
        assert c.authoritative_module
