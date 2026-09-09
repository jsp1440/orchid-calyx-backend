"""Tests for meta-orchestrator audit (Approved Task Priority 19)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.meta_orchestrator_audit import (
    ORCHESTRATOR_AUDIT_CRITERIA,
    OrchestratorAuditStatus,
    get_meta_orchestrator_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_meta_orchestrator_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "meta-orchestrator-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(ORCHESTRATOR_AUDIT_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(ORCHESTRATOR_AUDIT_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(OrchestratorAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(OrchestratorAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(OrchestratorAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(OrchestratorAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 14


# GAP criteria
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(OrchestratorAuditStatus.GAP):
        assert c.gap_description


# BLOCKED criteria
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(OrchestratorAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_no_generative_spend_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.BLOCKED)}
    assert "security_no_generative_spend" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(OrchestratorAuditStatus.BLOCKED):
        assert c.next_action


# OWNER_GATED criteria
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(OrchestratorAuditStatus.OWNER_GATED):
        assert c.next_action


def test_publication_approval_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.OWNER_GATED)}
    assert "human_gate_publication_approval" in ids


# Area coverage — all 7 areas
EXPECTED_AREAS = {"planning", "consequence", "authority", "capability", "human_gate", "security", "reservoir"}


def test_all_areas_covered():
    actual = {c.area for c in ORCHESTRATOR_AUDIT_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from orchestrator audit"


def test_planning_area_has_criteria():
    assert len(get_criteria_by_area("planning")) >= 3


def test_consequence_area_has_criteria():
    assert len(get_criteria_by_area("consequence")) >= 2


def test_authority_area_has_criteria():
    assert len(get_criteria_by_area("authority")) >= 2


def test_capability_area_has_criteria():
    assert len(get_criteria_by_area("capability")) >= 3


def test_human_gate_area_has_criteria():
    assert len(get_criteria_by_area("human_gate")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


def test_reservoir_area_has_criteria():
    assert len(get_criteria_by_area("reservoir")) >= 1


# Key criteria
def test_planning_mission_spec_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "planning_mission_spec" in ids


def test_planning_specialist_cap_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "planning_specialist_cap" in ids


def test_planning_reviewer_assignment_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "planning_reviewer_assignment" in ids


def test_consequence_risk_classes_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "consequence_risk_classes" in ids


def test_consequence_publication_candidate_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "consequence_publication_candidate" in ids


def test_authority_ceiling_static_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "authority_ceiling_static" in ids


def test_authority_independent_checker_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "authority_independent_checker" in ids


def test_capability_registry_static_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "capability_registry_static" in ids


def test_capability_empirical_routing_only_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "capability_empirical_routing_only" in ids


def test_capability_prohibited_set_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "capability_prohibited_set" in ids


def test_human_gate_high_consequence_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "human_gate_high_consequence_tasks" in ids


def test_security_agent_security_gateway_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(OrchestratorAuditStatus.READY)}
    assert "security_agent_security_gateway" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == OrchestratorAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(OrchestratorAuditStatus.READY):
        assert c.status == OrchestratorAuditStatus.READY


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
    assert parsed["schema_version"] == "meta-orchestrator-audit/v1"


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
    ids = [c.criterion_id for c in ORCHESTRATOR_AUDIT_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {OrchestratorAuditStatus.READY, OrchestratorAuditStatus.GAP,
             OrchestratorAuditStatus.BLOCKED, OrchestratorAuditStatus.OWNER_GATED}
    for c in ORCHESTRATOR_AUDIT_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in ORCHESTRATOR_AUDIT_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in ORCHESTRATOR_AUDIT_CRITERIA:
        assert c.authoritative_module
