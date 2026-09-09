"""Tests for deep orchestrate reservoir audit (Approved Task Priority 25)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.deep_orchestrate_audit import (
    DEEP_ORCH_CRITERIA,
    DeepOrchAuditStatus,
    get_deep_orch_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_deep_orch_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "deep-orchestrate-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(DEEP_ORCH_CRITERIA) >= 10


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(DEEP_ORCH_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(DeepOrchAuditStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(DeepOrchAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(DeepOrchAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(DeepOrchAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 10


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(DeepOrchAuditStatus.GAP):
        assert c.gap_description


def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(DeepOrchAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(DeepOrchAuditStatus.OWNER_GATED):
        assert c.next_action


def test_owner_gate_promotion_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeepOrchAuditStatus.OWNER_GATED)}
    assert "security_owner_gate_promotion" in ids


EXPECTED_AREAS = {"reservoir", "dedupe", "dependencies", "acceptance", "governance", "security"}


def test_all_areas_covered():
    actual = {c.area for c in DEEP_ORCH_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_reservoir_area_has_criteria():
    assert len(get_criteria_by_area("reservoir")) >= 2


def test_dedupe_area_has_criteria():
    assert len(get_criteria_by_area("dedupe")) >= 2


def test_dependencies_area_has_criteria():
    assert len(get_criteria_by_area("dependencies")) >= 1


def test_acceptance_area_has_criteria():
    assert len(get_criteria_by_area("acceptance")) >= 2


def test_governance_area_has_criteria():
    assert len(get_criteria_by_area("governance")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 1


def test_reservoir_depth_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeepOrchAuditStatus.READY)}
    assert "reservoir_approved_tasks_depth" in ids


def test_stable_task_keys_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeepOrchAuditStatus.READY)}
    assert "reservoir_stable_task_keys" in ids


def test_priority_ordering_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeepOrchAuditStatus.READY)}
    assert "reservoir_priority_ordering" in ids


def test_material_fingerprint_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeepOrchAuditStatus.READY)}
    assert "dedupe_material_fingerprint" in ids


def test_mission_state_fingerprint_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeepOrchAuditStatus.READY)}
    assert "dedupe_mission_state_fingerprint" in ids


def test_no_runtime_injection_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DeepOrchAuditStatus.READY)}
    assert "security_no_runtime_injection" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == DeepOrchAuditStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "deep-orchestrate-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output


def test_json_contains_no_coordinate_fields():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"latitude"', '"longitude"', '"lat":', '"lon":', '"lng":']:
        assert key not in output


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in DEEP_ORCH_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {DeepOrchAuditStatus.READY, DeepOrchAuditStatus.GAP,
             DeepOrchAuditStatus.BLOCKED, DeepOrchAuditStatus.OWNER_GATED}
    for c in DEEP_ORCH_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in DEEP_ORCH_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in DEEP_ORCH_CRITERIA:
        assert c.authoritative_module


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(DeepOrchAuditStatus.READY):
        assert c.status == DeepOrchAuditStatus.READY
