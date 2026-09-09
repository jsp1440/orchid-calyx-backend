"""Tests for capability registry audit (Approved Task Priority 23)."""

from __future__ import annotations

import json

from app.scientific_adapter_lab.capability_registry_audit import (
    CAPABILITY_REGISTRY_CRITERIA,
    CapabilityRegistryAuditStatus,
    get_capability_registry_audit,
    get_criteria_by_area,
    get_criteria_by_status,
    get_gaps,
    get_next_actions,
)

_AUDIT = get_capability_registry_audit()
_DICT = _AUDIT.to_dict()


def test_schema_version_present():
    assert _DICT["schema_version"] == "capability-registry-audit/v1"


def test_audit_date_present():
    assert _DICT["audit_date"] and len(_DICT["audit_date"]) == 10


def test_no_auto_publication():
    assert _AUDIT.no_auto_publication is True
    assert _DICT["no_auto_publication"] is True


def test_no_production_mutation():
    assert _AUDIT.no_production_mutation is True
    assert _DICT["no_production_mutation"] is True


def test_criteria_non_empty():
    assert len(CAPABILITY_REGISTRY_CRITERIA) >= 15


def test_summary_counts_sum_to_total():
    s = _DICT["summary"]
    assert s["ready"] + s["gap"] + s["blocked"] + s["owner_gated"] == s["total"]


def test_summary_total_matches_criteria_len():
    assert _DICT["summary"]["total"] == len(CAPABILITY_REGISTRY_CRITERIA)


# READY criteria
def test_ready_criteria_have_evidence():
    for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY):
        assert c.evidence, f"{c.criterion_id} READY but no evidence"


def test_ready_criteria_have_no_gap_description():
    for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY):
        assert c.gap_description is None


def test_ready_criteria_have_no_blocker_reason():
    for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY):
        assert c.blocker_reason is None


def test_ready_criteria_have_no_next_action():
    for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY):
        assert c.next_action is None


def test_audit_has_ready_items():
    assert _AUDIT.ready_count() >= 12


# GAP criteria
def test_gap_count_consistent():
    assert _AUDIT.gap_count() >= 0


def test_gap_criteria_have_gap_description():
    for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.GAP):
        assert c.gap_description


# BLOCKED criteria
def test_blocked_criteria_have_blocker_reason():
    for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.BLOCKED):
        assert c.blocker_reason


def test_audit_has_blocked_items():
    assert _AUDIT.blocked_count() >= 1


def test_live_provider_health_blocked():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.BLOCKED)}
    assert "provider_live_capability_health" in ids


def test_blocked_have_next_action():
    for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.BLOCKED):
        assert c.next_action


# OWNER_GATED criteria
def test_owner_gated_criteria_have_next_action():
    for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.OWNER_GATED):
        assert c.next_action


def test_scientific_authority_owner_gated():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.OWNER_GATED)}
    assert "security_owner_gate_scientific_authority" in ids


# Area coverage — all 7 areas
EXPECTED_AREAS = {"roles", "authority", "provider", "health", "endpoint", "security", "empirical"}


def test_all_areas_covered():
    actual = {c.area for c in CAPABILITY_REGISTRY_CRITERIA}
    for area in EXPECTED_AREAS:
        assert area in actual, f"Area '{area}' missing from capability registry audit"


def test_roles_area_has_criteria():
    assert len(get_criteria_by_area("roles")) >= 2


def test_authority_area_has_criteria():
    assert len(get_criteria_by_area("authority")) >= 3


def test_provider_area_has_criteria():
    assert len(get_criteria_by_area("provider")) >= 2


def test_health_area_has_criteria():
    assert len(get_criteria_by_area("health")) >= 2


def test_endpoint_area_has_criteria():
    assert len(get_criteria_by_area("endpoint")) >= 2


def test_security_area_has_criteria():
    assert len(get_criteria_by_area("security")) >= 2


def test_empirical_area_has_criteria():
    assert len(get_criteria_by_area("empirical")) >= 2


# Key criteria — roles
def test_canonical_allowlist_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "roles_canonical_allowlist" in ids


def test_registered_executor_dataclass_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "roles_registered_executor_dataclass" in ids


def test_known_registered_roles_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "roles_known_registered_roles" in ids


# Key criteria — authority
def test_authority_ceiling_static_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "authority_ceiling_static" in ids


def test_authority_ceiling_none_for_unregistered_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "authority_ceiling_none_for_unregistered" in ids


def test_authority_empirical_cannot_raise_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "authority_empirical_cannot_raise" in ids


def test_authority_no_external_side_effects_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "authority_no_external_side_effects" in ids


# Key criteria — provider
def test_provider_no_api_park_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "provider_no_api_park" in ids


def test_provider_work_intent_flag_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "provider_work_intent_flag" in ids


# Key criteria — health
def test_registry_status_dict_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "health_registry_status_dict" in ids


def test_capability_profile_registry_authority_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "health_capability_profile_registry_authority" in ids


# Key criteria — endpoint
def test_executor_key_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "endpoint_executor_key" in ids


def test_role_profiles_per_owner_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "endpoint_role_profiles_per_owner" in ids


# Key criteria — security
def test_no_open_registration_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "security_no_open_registration" in ids


# Key criteria — empirical
def test_empirical_stats_outcome_counts_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "empirical_stats_outcome_counts" in ids


def test_empirical_descriptive_routing_context_ready():
    ids = {c.criterion_id for c in _AUDIT.by_status(CapabilityRegistryAuditStatus.READY)}
    assert "empirical_descriptive_routing_context" in ids


# Helpers
def test_get_gaps_returns_only_gap_status():
    for c in get_gaps():
        assert c.status == CapabilityRegistryAuditStatus.GAP


def test_get_criteria_by_status_ready():
    for c in get_criteria_by_status(CapabilityRegistryAuditStatus.READY):
        assert c.status == CapabilityRegistryAuditStatus.READY


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
    assert parsed["schema_version"] == "capability-registry-audit/v1"


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
    ids = [c.criterion_id for c in CAPABILITY_REGISTRY_CRITERIA]
    assert len(ids) == len(set(ids))


def test_all_criteria_have_valid_status():
    valid = {CapabilityRegistryAuditStatus.READY, CapabilityRegistryAuditStatus.GAP,
             CapabilityRegistryAuditStatus.BLOCKED, CapabilityRegistryAuditStatus.OWNER_GATED}
    for c in CAPABILITY_REGISTRY_CRITERIA:
        assert c.status in valid


def test_all_criteria_have_evidence():
    for c in CAPABILITY_REGISTRY_CRITERIA:
        assert c.evidence


def test_all_criteria_have_authoritative_module():
    for c in CAPABILITY_REGISTRY_CRITERIA:
        assert c.authoritative_module
