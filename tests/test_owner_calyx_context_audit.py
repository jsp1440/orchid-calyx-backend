"""Tests for owner Calyx program context audit (Approved Task Priority 16)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.owner_calyx_context_audit import (
    CONTEXT_AUDIT_CRITERIA,
    ContextAuditStatus,
    get_owner_calyx_context_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_owner_calyx_context_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "owner-calyx-context-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(CONTEXT_AUDIT_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(CONTEXT_AUDIT_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(ContextAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(ContextAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(ContextAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(ContextAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 12


# GAP criteria
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(ContextAuditStatus.GAP):
        assert c.gap_description


# BLOCKED criteria
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(ContextAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(ContextAuditStatus.BLOCKED):
        assert c.next_action


# OWNER_GATED criteria
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(ContextAuditStatus.OWNER_GATED):
        assert c.next_action


def test_audit_has_owner_gated_items():
    assert _AUDIT.owner_gated_count() >= 2


def test_taxonomy_activation_is_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.OWNER_GATED)}
    assert "owner_gate_taxonomy_activation" in ids


def test_main_merge_is_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.OWNER_GATED)}
    assert "owner_gate_main_merge" in ids


def test_evidence_publication_is_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.OWNER_GATED)}
    assert "owner_gate_evidence_publication" in ids


# Area coverage — all 7 areas
EXPECTED_AREAS = {"repository", "ci", "provider", "completion_graph", "module", "blocker", "owner_gate"}


def test_all_areas_covered():
    actual = {c.area for c in CONTEXT_AUDIT_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from context audit"


def test_repository_area_has_criteria():
    assert len(get_criteria_by_area("repository")) >= 2


def test_ci_area_has_criteria():
    assert len(get_criteria_by_area("ci")) >= 2


def test_provider_area_has_criteria():
    assert len(get_criteria_by_area("provider")) >= 2


def test_completion_graph_area_has_criteria():
    assert len(get_criteria_by_area("completion_graph")) >= 2


def test_module_area_has_criteria():
    assert len(get_criteria_by_area("module")) >= 3


def test_blocker_area_has_criteria():
    assert len(get_criteria_by_area("blocker")) >= 2


def test_owner_gate_area_has_criteria():
    assert len(get_criteria_by_area("owner_gate")) >= 2


# Key criteria
def test_repository_approved_task_reservoir_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.READY)}
    assert "repository_approved_task_reservoir" in ids


def test_repository_agent_operating_memory_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.READY)}
    assert "repository_agent_operating_memory" in ids


def test_ci_required_checks_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.READY)}
    assert "ci_required_checks" in ids


def test_ci_live_github_check_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.BLOCKED)}
    assert "ci_live_github_check" in ids


def test_provider_runtime_configuration_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.READY)}
    assert "provider_runtime_configuration" in ids


def test_provider_no_api_park_action_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.READY)}
    assert "provider_no_api_park_action" in ids


def test_completion_graph_program_snapshot_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.READY)}
    assert "completion_graph_program_snapshot" in ids


def test_completion_graph_dependency_ordering_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.READY)}
    assert "completion_graph_dependency_ordering" in ids


def test_module_factory_policy_risk_gate_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.READY)}
    assert "module_factory_policy_risk_gate" in ids


def test_module_agent_security_gateway_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.READY)}
    assert "module_agent_security_gateway" in ids


def test_blocker_no_api_mode_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.READY)}
    assert "blocker_no_api_mode" in ids


def test_blocker_database_url_missing_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(ContextAuditStatus.BLOCKED)}
    assert "blocker_database_url_missing" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == ContextAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(ContextAuditStatus.READY):
        assert c.status == ContextAuditStatus.READY


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["area"]
        assert action["title"]
        assert action["status"]
        assert action["next_action"]


# Serialization
def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "owner-calyx-context-audit/v1"


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
    ids = [c.criterion_id for c in CONTEXT_AUDIT_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {ContextAuditStatus.READY, ContextAuditStatus.GAP,
             ContextAuditStatus.BLOCKED, ContextAuditStatus.OWNER_GATED}
    for c in CONTEXT_AUDIT_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in CONTEXT_AUDIT_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in CONTEXT_AUDIT_CRITERIA:
        assert c.authoritative_module
