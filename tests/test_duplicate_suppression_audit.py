"""Tests for duplicate suppression audit (Approved Task Priority 27)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.duplicate_suppression_audit import (
    DUPE_SUPPRESSION_CRITERIA,
    DupeSuppressionStatus,
    get_duplicate_suppression_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_duplicate_suppression_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "duplicate-suppression-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(DUPE_SUPPRESSION_CRITERIA) >= 8


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(DUPE_SUPPRESSION_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(DupeSuppressionStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(DupeSuppressionStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(DupeSuppressionStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(DupeSuppressionStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 8


def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(DupeSuppressionStatus.GAP):
        assert c.gap_description


def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(DupeSuppressionStatus.BLOCKED):
        assert c.blocker_reason


def test_owner_gated_have_next_action():
    for c in _AUDIT.by_status(DupeSuppressionStatus.OWNER_GATED):
        assert c.next_action


def test_suppression_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(DupeSuppressionStatus.OWNER_GATED)}
    assert "security_suppression_owner_gated" in ids


EXPECTED_AREAS = {"fingerprint", "pr_head_dedupe", "dispatch_suppression", "unchanged_run_prevention", "security"}


def test_all_areas_covered():
    actual = {c.area for c in DUPE_SUPPRESSION_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_fingerprint_area_has_criteria():
    assert len(get_criteria_by_area("fingerprint")) >= 2


def test_pr_head_dedupe_area_has_criteria():
    assert len(get_criteria_by_area("pr_head_dedupe")) >= 2


def test_dispatch_suppression_area_has_criteria():
    assert len(get_criteria_by_area("dispatch_suppression")) >= 2


def test_unchanged_run_prevention_area_has_criteria():
    assert len(get_criteria_by_area("unchanged_run_prevention")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 1


def test_material_change_fingerprint_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DupeSuppressionStatus.READY)}
    assert "fingerprint_material_change" in ids


def test_factory_decision_fingerprint_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DupeSuppressionStatus.READY)}
    assert "fingerprint_factory_decision" in ids


def test_mission_state_validation_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DupeSuppressionStatus.READY)}
    assert "fingerprint_mission_state_validation" in ids


def test_enqueue_dedupe_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DupeSuppressionStatus.READY)}
    assert "pr_head_dedupe_enqueue" in ids


def test_completion_receipt_head_sha_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DupeSuppressionStatus.READY)}
    assert "pr_head_dedupe_completion_receipt" in ids


def test_dispatch_park_provider_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DupeSuppressionStatus.READY)}
    assert "dispatch_suppression_park_provider" in ids


def test_checker_verdict_dedup_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DupeSuppressionStatus.READY)}
    assert "dispatch_suppression_checker_verdict" in ids


def test_unchanged_run_fingerprint_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DupeSuppressionStatus.READY)}
    assert "unchanged_run_mission_state_fingerprint" in ids


def test_immutable_artifact_idempotency_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DupeSuppressionStatus.READY)}
    assert "unchanged_run_immutable_artifact_idempotency" in ids


def test_no_credential_in_fingerprint_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(DupeSuppressionStatus.READY)}
    assert "security_no_credential_in_fingerprint" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == DupeSuppressionStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "duplicate-suppression-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in DUPE_SUPPRESSION_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {DupeSuppressionStatus.READY, DupeSuppressionStatus.GAP,
             DupeSuppressionStatus.BLOCKED, DupeSuppressionStatus.OWNER_GATED}
    for c in DUPE_SUPPRESSION_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in DUPE_SUPPRESSION_CRITERIA:
        assert c.evidence


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(DupeSuppressionStatus.READY):
        assert c.status == DupeSuppressionStatus.READY
