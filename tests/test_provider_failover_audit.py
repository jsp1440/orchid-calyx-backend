"""Tests for provider failover audit (Approved Task Priority 32)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.provider_failover_audit import (
    PROVIDER_FAILOVER_CRITERIA,
    ProviderFailoverAuditStatus,
    get_provider_failover_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_provider_failover_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "provider-failover-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True


def test_criteria_non_empty():
    assert len(PROVIDER_FAILOVER_CRITERIA) >= 12


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(PROVIDER_FAILOVER_CRITERIA)


def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY):
        assert c.evidence


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 10


def test_audit_has_no_gaps():
    assert _AUDIT.gap_count() == 0


def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(ProviderFailoverAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_live_failover_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.BLOCKED)}
    assert "non_thrashing_live_failover_blocked" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(ProviderFailoverAuditStatus.BLOCKED):
        assert c.next_action


def test_owner_gated_have_next_action():
    for c in _AUDIT.by_status(ProviderFailoverAuditStatus.OWNER_GATED):
        assert c.next_action


def test_paid_provider_restoration_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.OWNER_GATED)}
    assert "governance_no_api_spending_required" in ids


EXPECTED_AREAS = {
    "bounded_fallback",
    "fail_closed_security",
    "redaction",
    "non_thrashing",
    "governance_independence",
}


def test_all_areas_covered():
    actual = {c.area for c in PROVIDER_FAILOVER_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual


def test_bounded_fallback_area_has_criteria():
    assert len(get_criteria_by_area("bounded_fallback")) >= 3


def test_fail_closed_security_area_has_criteria():
    assert len(get_criteria_by_area("fail_closed_security")) >= 3


def test_redaction_area_has_criteria():
    assert len(get_criteria_by_area("redaction")) >= 2


def test_non_thrashing_area_has_criteria():
    assert len(get_criteria_by_area("non_thrashing")) >= 2


def test_governance_independence_area_has_criteria():
    assert len(get_criteria_by_area("governance_independence")) >= 3


def test_park_provider_required_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY)}
    assert "bounded_park_provider_required" in ids


def test_provider_free_path_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY)}
    assert "bounded_provider_free_path" in ids


def test_factory_park_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY)}
    assert "bounded_factory_park" in ids


def test_no_api_mode_fail_closed_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY)}
    assert "fail_closed_no_api_mode" in ids


def test_security_guard_not_weakened_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY)}
    assert "fail_closed_security_guard" in ids


def test_provider_disabled_engineering_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY)}
    assert "fail_closed_provider_disabled_engineering" in ids


def test_credential_not_logged_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY)}
    assert "redaction_credential_not_logged" in ids


def test_provider_status_no_secrets_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY)}
    assert "redaction_provider_status_no_secrets" in ids


def test_park_not_retry_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY)}
    assert "non_thrashing_park_not_retry" in ids


def test_governance_independent_of_provider_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY)}
    assert "governance_independent_of_provider" in ids


def test_owner_gate_no_provider_bypass_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(ProviderFailoverAuditStatus.READY)}
    assert "governance_owner_gate_no_provider_bypass" in ids


def test_get_gaps_returns_only_gap():
    for c in get_gaps():
        assert c.status == ProviderFailoverAuditStatus.GAP


def test_get_next_actions_non_empty():
    assert get_next_actions()


def test_get_next_actions_have_required_fields():
    for action in get_next_actions():
        assert action["criterion_id"]
        assert action["next_action"]


def test_serialize_as_json_no_error():
    output = _AUDIT.serialize_as_json()
    parsed = json.loads(output)
    assert parsed["schema_version"] == "provider-failover-audit/v1"


def test_to_dict_all_criteria_serializable():
    for c in _AUDIT.criteria:
        assert json.dumps(c.to_dict())


def test_json_contains_no_credential_keys():
    output = _AUDIT.serialize_as_json().lower()
    for key in ['"password"', '"secret"', '"api_key"', '"private_key"', '"auth_token"', '"access_token"']:
        assert key not in output, f"Credential key {key!r} found in output"


def test_all_criterion_ids_unique():
    ids = [c.criterion_id for c in PROVIDER_FAILOVER_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {ProviderFailoverAuditStatus.READY, ProviderFailoverAuditStatus.GAP,
             ProviderFailoverAuditStatus.BLOCKED, ProviderFailoverAuditStatus.OWNER_GATED}
    for c in PROVIDER_FAILOVER_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in PROVIDER_FAILOVER_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in PROVIDER_FAILOVER_CRITERIA:
        assert c.authoritative_module


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(ProviderFailoverAuditStatus.READY):
        assert c.status == ProviderFailoverAuditStatus.READY


def test_criterion_frozen():
    c = PROVIDER_FAILOVER_CRITERIA[0]
    try:
        c.criterion_id = "mutated"  # type: ignore[misc]
        assert False, "Should not be mutable"
    except (AttributeError, TypeError):
        pass


def test_security_guard_evidence_cites_agents_md():
    criterion = next(
        c for c in PROVIDER_FAILOVER_CRITERIA
        if c.criterion_id == "fail_closed_security_guard"
    )
    assert "AGENTS.md" in criterion.evidence or "CLAUDE.md" in criterion.evidence


def test_paid_provider_owner_evidence_cites_boundary():
    criterion = next(
        c for c in PROVIDER_FAILOVER_CRITERIA
        if c.criterion_id == "governance_no_api_spending_required"
    )
    assert "spending_provider_restoration" in criterion.evidence
    assert "owner_decision_required=True" in criterion.evidence
