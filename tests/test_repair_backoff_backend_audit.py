"""Tests for backend repair-backoff invariant audit (Approved Task Priority 29)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.repair_backoff_backend_audit import (
    REPAIR_BACKOFF_CRITERIA,
    RepairBackoffAuditStatus,
    get_repair_backoff_backend_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_repair_backoff_backend_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "repair-backoff-backend-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(REPAIR_BACKOFF_CRITERIA) >= 12


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(REPAIR_BACKOFF_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 12


def test_audit_has_no_gaps():
    assert _AUDIT.gap_count() == 0


def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(RepairBackoffAuditStatus.GAP):
        assert c.gap_description


def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(RepairBackoffAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_owner_gated_have_next_action():
    for c in _AUDIT.by_status(RepairBackoffAuditStatus.OWNER_GATED):
        assert c.next_action


def test_production_db_mutation_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.OWNER_GATED)}
    assert "security_production_db_mutation_forbidden" in ids


EXPECTED_AREAS = {"bounded_repair", "dispatch_invariants", "repair_authorization", "backoff_mechanism", "security"}


def test_all_areas_covered():
    actual = {c.area for c in REPAIR_BACKOFF_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_bounded_repair_area_has_criteria():
    assert len(get_criteria_by_area("bounded_repair")) >= 3


def test_dispatch_invariants_area_has_criteria():
    assert len(get_criteria_by_area("dispatch_invariants")) >= 5


def test_repair_authorization_area_has_criteria():
    assert len(get_criteria_by_area("repair_authorization")) >= 2


def test_backoff_mechanism_area_has_criteria():
    assert len(get_criteria_by_area("backoff_mechanism")) >= 3


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


def test_max_attempts_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "bounded_repair_max_attempts" in ids


def test_halt_retry_limit_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "bounded_repair_halt_retry_limit" in ids


def test_agents_md_rule_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "bounded_repair_agents_md_rule" in ids


def test_autonomous_merge_forbidden_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "dispatch_autonomous_merge_forbidden" in ids


def test_deployment_forbidden_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "dispatch_deployment_forbidden" in ids


def test_kg_mutation_forbidden_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "dispatch_kg_mutation_forbidden" in ids


def test_publication_forbidden_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "dispatch_publication_forbidden" in ids


def test_owner_gate_preserved_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "dispatch_owner_gate_preserved" in ids


def test_repair_auth_required_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "repair_auth_required" in ids


def test_blocked_approval_parking_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "repair_blocked_approval_parking" in ids


def test_retry_backoff_action_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "backoff_retry_backoff_action" in ids


def test_dedup_no_op_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "backoff_dedup_no_op" in ids


def test_stale_head_closed_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "backoff_stale_head_closed" in ids


def test_halt_infrastructure_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffAuditStatus.READY)}
    assert "security_halt_infrastructure" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == RepairBackoffAuditStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "repair-backoff-backend-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output, f"Credential key {key!r} found in output"


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in REPAIR_BACKOFF_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {RepairBackoffAuditStatus.READY, RepairBackoffAuditStatus.GAP,
             RepairBackoffAuditStatus.BLOCKED, RepairBackoffAuditStatus.OWNER_GATED}
    for c in REPAIR_BACKOFF_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in REPAIR_BACKOFF_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in REPAIR_BACKOFF_CRITERIA:
        assert c.authoritative_module


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(RepairBackoffAuditStatus.READY):
        assert c.status == RepairBackoffAuditStatus.READY


def test_criterion_frozen():
    c = REPAIR_BACKOFF_CRITERIA[0]
    try:
        c.criterion_id = "mutated"  # type: ignore[misc]
        assert False, "Should not be mutable"
    except (AttributeError, TypeError):
        pass


def test_audit_summary_json_structure():
    s = _DICT["summary"]
    assert "total" in s
    assert "ready" in s
    assert "gap" in s
    assert "blocked" in s
    assert "owner_gated" in s


def test_no_production_db_mutation_in_repair_path():
    owner_gated = _AUDIT.by_status(RepairBackoffAuditStatus.OWNER_GATED)
    ids = {c.criterion_id for c in owner_gated}
    assert "security_production_db_mutation_forbidden" in ids
    c = next(x for x in owner_gated if x.criterion_id == "security_production_db_mutation_forbidden")
    assert "owner" in c.evidence.lower() or "owner" in (c.next_action or "").lower()


def test_dispatch_invariants_all_ready():
    dispatch = get_criteria_by_area("dispatch_invariants")
    for c in dispatch:
        assert c.status == RepairBackoffAuditStatus.READY


def test_bounded_repair_all_ready():
    bounded = get_criteria_by_area("bounded_repair")
    for c in bounded:
        assert c.status == RepairBackoffAuditStatus.READY


def test_repair_authorization_all_ready():
    auth = get_criteria_by_area("repair_authorization")
    for c in auth:
        assert c.status == RepairBackoffAuditStatus.READY


def test_backoff_mechanism_all_ready():
    backoff = get_criteria_by_area("backoff_mechanism")
    for c in backoff:
        assert c.status == RepairBackoffAuditStatus.READY
