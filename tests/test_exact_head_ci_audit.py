"""Tests for exact-head CI audit (Approved Task Priority 33)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.exact_head_ci_audit import (
    EXACT_HEAD_CI_CRITERIA,
    ExactHeadCiAuditStatus,
    get_exact_head_ci_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_exact_head_ci_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "exact-head-ci-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(EXACT_HEAD_CI_CRITERIA) >= 12


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(EXACT_HEAD_CI_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 11


def test_audit_has_no_gaps():
    assert _AUDIT.gap_count() == 0


def test_audit_has_no_blocked():
    assert _AUDIT.blocked_count() == 0


def test_audit_has_owner_gated_items():
    assert _AUDIT.owner_gated_count() >= 1


def test_owner_gated_have_next_action():
    for c in _AUDIT.by_status(ExactHeadCiAuditStatus.OWNER_GATED):
        assert c.next_action


def test_no_auto_merge_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.OWNER_GATED)}
    assert "security_no_auto_merge" in ids


EXPECTED_AREAS = {
    "head_binding",
    "rejected_conclusions",
    "substantive_checks",
    "deduplication",
    "security",
}


def test_all_areas_covered():
    actual = {c.area for c in EXACT_HEAD_CI_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_head_binding_area_has_criteria():
    assert len(get_criteria_by_area("head_binding")) >= 3


def test_rejected_conclusions_area_has_criteria():
    assert len(get_criteria_by_area("rejected_conclusions")) >= 3


def test_substantive_checks_area_has_criteria():
    assert len(get_criteria_by_area("substantive_checks")) >= 2


def test_deduplication_area_has_criteria():
    assert len(get_criteria_by_area("deduplication")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


def test_validate_head_sha_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "head_binding_validate_head_sha" in ids


def test_event_key_minimum_sha_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "head_binding_event_key_minimum_sha" in ids


def test_stale_fail_closed_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "head_binding_stale_fail_closed" in ids


def test_completion_receipt_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "head_binding_completion_receipt" in ids


def test_cancelled_infrastructure_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "rejected_cancelled_infrastructure" in ids


def test_action_required_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "rejected_action_required" in ids


def test_skipped_transient_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "rejected_skipped_transient" in ids


def test_stale_conclusion_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "rejected_stale_conclusion" in ids


def test_substantive_success_only_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "substantive_success_only" in ids


def test_substantive_pending_await_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "substantive_pending_await" in ids


def test_dedup_idempotency_key_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "dedup_idempotency_key" in ids


def test_dedup_stale_head_marked_seen_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "dedup_stale_head_marked_seen" in ids


def test_infrastructure_halt_no_repair_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ExactHeadCiAuditStatus.READY)}
    assert "security_infrastructure_halt_no_repair" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == ExactHeadCiAuditStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "exact-head-ci-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output, f"Credential key {key!r} found in output"


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in EXACT_HEAD_CI_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {ExactHeadCiAuditStatus.READY, ExactHeadCiAuditStatus.GAP,
             ExactHeadCiAuditStatus.BLOCKED, ExactHeadCiAuditStatus.OWNER_GATED}
    for c in EXACT_HEAD_CI_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in EXACT_HEAD_CI_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in EXACT_HEAD_CI_CRITERIA:
        assert c.authoritative_module


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(ExactHeadCiAuditStatus.READY):
        assert c.status == ExactHeadCiAuditStatus.READY


def test_criterion_frozen():
    c = EXACT_HEAD_CI_CRITERIA[0]
    try:
        c.criterion_id = "mutated"  # type: ignore[misc]
        assert False, "Should not be mutable"
    except (AttributeError, TypeError):
        pass


def test_validate_head_binding_evidence_cites_fail_closed():
    criterion = next(
        c for c in EXACT_HEAD_CI_CRITERIA
        if c.criterion_id == "head_binding_validate_head_sha"
    )
    assert "FAIL_CLOSED_STALE_HEAD" in criterion.evidence


def test_event_key_evidence_cites_minimum_length():
    criterion = next(
        c for c in EXACT_HEAD_CI_CRITERIA
        if c.criterion_id == "head_binding_event_key_minimum_sha"
    )
    assert "7" in criterion.evidence
    assert "EVENT_KEY_HEAD_SHA_INVALID" in criterion.evidence


def test_cancelled_evidence_cites_infrastructure_conclusions():
    criterion = next(
        c for c in EXACT_HEAD_CI_CRITERIA
        if c.criterion_id == "rejected_cancelled_infrastructure"
    )
    assert "_INFRASTRUCTURE_CONCLUSIONS" in criterion.evidence
    assert "cancelled" in criterion.evidence


def test_skipped_evidence_cites_transient_conclusions():
    criterion = next(
        c for c in EXACT_HEAD_CI_CRITERIA
        if c.criterion_id == "rejected_skipped_transient"
    )
    assert "_TRANSIENT_CONCLUSIONS" in criterion.evidence
    assert "MAX_TRANSIENT_RETRIES" in criterion.evidence


def test_success_only_evidence_cites_neutral_as_failure():
    criterion = next(
        c for c in EXACT_HEAD_CI_CRITERIA
        if c.criterion_id == "substantive_success_only"
    )
    assert "neutral" in criterion.evidence
    assert "_FAILURE_CONCLUSIONS" in criterion.evidence


def test_idempotency_key_evidence_cites_sha256():
    criterion = next(
        c for c in EXACT_HEAD_CI_CRITERIA
        if c.criterion_id == "dedup_idempotency_key"
    )
    assert "sha256" in criterion.evidence.lower() or "SHA-256" in criterion.evidence


def test_no_auto_merge_evidence_cites_permission_error():
    criterion = next(
        c for c in EXACT_HEAD_CI_CRITERIA
        if c.criterion_id == "security_no_auto_merge"
    )
    assert "PermissionError" in criterion.evidence
    assert "FORBIDDEN" in criterion.evidence


def test_infrastructure_halt_evidence_cites_no_repair():
    criterion = next(
        c for c in EXACT_HEAD_CI_CRITERIA
        if c.criterion_id == "security_infrastructure_halt_no_repair"
    )
    assert "HALT_INFRASTRUCTURE" in criterion.evidence
    assert "owner review" in criterion.evidence.lower()


def test_head_binding_all_ready():
    head_binding = get_criteria_by_area("head_binding")
    assert head_binding
    for c in head_binding:
        assert c.status == ExactHeadCiAuditStatus.READY


def test_rejected_conclusions_all_ready():
    rejected = get_criteria_by_area("rejected_conclusions")
    assert rejected
    for c in rejected:
        assert c.status == ExactHeadCiAuditStatus.READY


def test_deduplication_all_ready():
    dedup = get_criteria_by_area("deduplication")
    assert dedup
    for c in dedup:
        assert c.status == ExactHeadCiAuditStatus.READY
