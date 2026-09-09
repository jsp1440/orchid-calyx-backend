"""Tests for frontend repair-backoff invariant audit (Approved Task Priority 31)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.repair_backoff_frontend_audit import (
    REPAIR_BACKOFF_FRONTEND_CRITERIA,
    RepairBackoffFrontendAuditStatus,
    get_repair_backoff_frontend_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_repair_backoff_frontend_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "repair-backoff-frontend-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(REPAIR_BACKOFF_FRONTEND_CRITERIA) >= 13


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(REPAIR_BACKOFF_FRONTEND_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 13


def test_audit_has_no_gaps():
    assert _AUDIT.gap_count() == 0


def test_audit_has_no_blocked():
    assert _AUDIT.blocked_count() == 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.GAP):
        assert c.gap_description


def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_owner_gated_have_next_action():
    for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.OWNER_GATED):
        assert c.next_action


def test_owner_protection_preserved_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.OWNER_GATED)}
    assert "security_repair_owner_protection_preserved" in ids


EXPECTED_AREAS = {"healer", "scheduler", "dispatcher", "settlement", "security"}


def test_all_areas_covered():
    actual = {c.area for c in REPAIR_BACKOFF_FRONTEND_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_healer_area_has_criteria():
    assert len(get_criteria_by_area("healer")) >= 3


def test_scheduler_area_has_criteria():
    assert len(get_criteria_by_area("scheduler")) >= 3


def test_dispatcher_area_has_criteria():
    assert len(get_criteria_by_area("dispatcher")) >= 3


def test_settlement_area_has_criteria():
    assert len(get_criteria_by_area("settlement")) >= 3


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


def test_repair_backoff_state_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "healer_repair_backoff_state" in ids


def test_enter_repair_backoff_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "healer_enter_repair_backoff" in ids


def test_recover_from_backoff_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "healer_recover_from_backoff" in ids


def test_is_ready_excludes_backoff_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "scheduler_is_ready_excludes_backoff" in ids


def test_refill_excludes_backoff_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "scheduler_refill_excludes_backoff" in ids


def test_cycle_bounded_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "scheduler_cycle_bounded" in ids


def test_repair_backoff_anomaly_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "dispatcher_repair_backoff_anomaly" in ids


def test_queue_backoff_anomaly_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "dispatcher_queue_backoff_anomaly" in ids


def test_owner_gate_isolation_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "dispatcher_owner_gate_isolation" in ids


def test_failed_not_re_queued_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "settlement_failed_not_re_queued" in ids


def test_retry_requires_api_call_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "settlement_retry_requires_api_call" in ids


def test_cancelled_not_re_admitted_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "settlement_cancelled_not_re_admitted" in ids


def test_autonomy_not_authorized_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(RepairBackoffFrontendAuditStatus.READY)}
    assert "security_autonomy_not_authorized" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == RepairBackoffFrontendAuditStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "repair-backoff-frontend-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output, f"Credential key {key!r} found in output"


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in REPAIR_BACKOFF_FRONTEND_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {RepairBackoffFrontendAuditStatus.READY, RepairBackoffFrontendAuditStatus.GAP,
             RepairBackoffFrontendAuditStatus.BLOCKED, RepairBackoffFrontendAuditStatus.OWNER_GATED}
    for c in REPAIR_BACKOFF_FRONTEND_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in REPAIR_BACKOFF_FRONTEND_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in REPAIR_BACKOFF_FRONTEND_CRITERIA:
        assert c.authoritative_module


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(RepairBackoffFrontendAuditStatus.READY):
        assert c.status == RepairBackoffFrontendAuditStatus.READY


def test_criterion_frozen():
    c = REPAIR_BACKOFF_FRONTEND_CRITERIA[0]
    try:
        c.criterion_id = "mutated"  # type: ignore[misc]
        assert False, "Should not be mutable"
    except (AttributeError, TypeError):
        pass


def test_healer_no_auto_recovery_evidence():
    criterion = next(
        c for c in REPAIR_BACKOFF_FRONTEND_CRITERIA
        if c.criterion_id == "healer_recover_from_backoff"
    )
    assert "NOT_IN_BACKOFF" in criterion.evidence
    assert "explicit" in criterion.evidence.lower() or "requires" in criterion.evidence.lower()


def test_dispatcher_engineering_anomaly_no_owner_interrupt():
    criterion = next(
        c for c in REPAIR_BACKOFF_FRONTEND_CRITERIA
        if c.criterion_id == "dispatcher_repair_backoff_anomaly"
    )
    assert "engineering_exception" in criterion.evidence
    assert "owner_decision_required=False" in criterion.evidence


def test_settlement_dedup_key_prevents_re_insertion():
    criterion = next(
        c for c in REPAIR_BACKOFF_FRONTEND_CRITERIA
        if c.criterion_id == "settlement_failed_not_re_queued"
    )
    assert "dedup_key" in criterion.evidence or "UNIQUE" in criterion.evidence


def test_healer_all_ready():
    healer = get_criteria_by_area("healer")
    for c in healer:
        assert c.status == RepairBackoffFrontendAuditStatus.READY


def test_settlement_all_ready():
    settlement = get_criteria_by_area("settlement")
    for c in settlement:
        assert c.status == RepairBackoffFrontendAuditStatus.READY
