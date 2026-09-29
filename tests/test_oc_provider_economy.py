"""Tests for OC-PROVIDER-ECONOMY-001 — role-specific provider registry.

Proves all 8 acceptance criteria from issue #1137:
1. Kimi eligible for bounded task class without expanded authority
2. Perplexity output stays source-discovery context only, never evidence
3. Twin cannot bypass Agent/MCP Security Gateway
4. Unavailable/no-API provider represented honestly (NOT_AVAILABLE/UNKNOWN)
5. subscription-vs-API billing state is explicit
6. Provider selection deterministic from task class + health
7. Missing cost metadata is UNKNOWN, never zero
8. Fallback/tiering does not alter acceptance gates
"""

import json

import pytest

from scripts.oc_provider_economy import (
    PROVIDER_REGISTRY,
    SCHEMA_VERSION,
    ApiAvailability,
    ProviderHealth,
    TaskClass,
    build_provider_readiness_report,
    check_authority_not_expanded,
    perplexity_output_is_source_discovery_only,
    select_provider_for_task,
    twin_must_use_security_gateway,
)

# ---------------------------------------------------------------------------
# Registry sanity
# ---------------------------------------------------------------------------


def test_all_four_providers_present():
    assert set(PROVIDER_REGISTRY) >= {"kimi", "perplexity", "twin", "magai"}


def test_schema_version_present():
    assert SCHEMA_VERSION == "oc-provider-economy/v1"


def test_every_provider_has_subscription_vs_api_billing():
    for pid, profile in PROVIDER_REGISTRY.items():
        assert profile.subscription_vs_api_billing, f"{pid} missing billing note"


def test_every_provider_has_notes():
    for pid, profile in PROVIDER_REGISTRY.items():
        assert profile.notes, f"{pid} missing notes"


# ---------------------------------------------------------------------------
# AC-1: Kimi eligible for bounded task class without expanded authority
# ---------------------------------------------------------------------------


def test_kimi_eligible_for_coding_task_class():
    kimi = PROVIDER_REGISTRY["kimi"]
    assert TaskClass.CODING_REPOSITORY_EDIT in kimi.task_classes


def test_kimi_eligible_for_classification_task_class():
    kimi = PROVIDER_REGISTRY["kimi"]
    assert TaskClass.READ_ONLY_CLASSIFICATION in kimi.task_classes


def test_kimi_authority_ceiling_does_not_exceed_repository_code_execution():
    kimi = PROVIDER_REGISTRY["kimi"]
    assert kimi.authority_ceiling == "repository_code_execution"


def test_kimi_authority_check_passes_at_ceiling():
    check_authority_not_expanded("kimi", "repository_code_execution")  # must not raise


def test_kimi_authority_check_passes_below_ceiling():
    check_authority_not_expanded("kimi", "read_only")  # must not raise


def test_kimi_authority_check_blocks_production_change():
    with pytest.raises(ValueError, match="never expand authority"):
        check_authority_not_expanded("kimi", "production_change")


def test_kimi_selected_for_coding():
    result = select_provider_for_task(TaskClass.CODING_REPOSITORY_EDIT)
    assert result.selected_provider_id == "kimi"
    assert result.authority_ceiling == "repository_code_execution"


def test_kimi_selected_for_read_only_classification():
    result = select_provider_for_task(TaskClass.READ_ONLY_CLASSIFICATION)
    assert result.selected_provider_id == "kimi"


def test_kimi_api_available():
    kimi = PROVIDER_REGISTRY["kimi"]
    assert kimi.api_availability == ApiAvailability.AVAILABLE
    assert kimi.is_available is True


# ---------------------------------------------------------------------------
# AC-2: Perplexity output is source-discovery context only, never evidence
# ---------------------------------------------------------------------------


def test_perplexity_evidence_status_is_source_discovery_context_only():
    perp = PROVIDER_REGISTRY["perplexity"]
    assert perp.evidence_status == "source_discovery_context_only"


def test_perplexity_output_is_source_discovery_only_helper():
    assert perplexity_output_is_source_discovery_only("perplexity") is True


def test_perplexity_output_helper_false_for_other_providers():
    assert perplexity_output_is_source_discovery_only("kimi") is False
    assert perplexity_output_is_source_discovery_only("twin") is False


def test_perplexity_authority_ceiling_is_read_only():
    perp = PROVIDER_REGISTRY["perplexity"]
    assert perp.authority_ceiling == "read_only"


def test_perplexity_selected_for_web_retrieval():
    result = select_provider_for_task(TaskClass.RESEARCH_WEB_RETRIEVAL)
    assert result.selected_provider_id == "perplexity"
    assert result.evidence_status == "source_discovery_context_only"


def test_perplexity_cannot_exceed_read_only_authority():
    with pytest.raises(ValueError):
        check_authority_not_expanded("perplexity", "bounded_workspace_mutation")


def test_perplexity_notes_mention_not_canonical_evidence():
    perp = PROVIDER_REGISTRY["perplexity"]
    note = perp.notes.lower()
    assert "source" in note and "evidence" in note


# ---------------------------------------------------------------------------
# AC-3: Twin cannot bypass Agent/MCP Security Gateway
# ---------------------------------------------------------------------------


def test_twin_requires_security_gateway():
    twin = PROVIDER_REGISTRY["twin"]
    assert twin.gateway_required is True


def test_twin_security_gateway_helper():
    assert twin_must_use_security_gateway("twin") is True


def test_twin_gateway_helper_false_for_kimi():
    assert twin_must_use_security_gateway("kimi") is False


def test_twin_gateway_helper_false_for_perplexity():
    assert twin_must_use_security_gateway("perplexity") is False


def test_twin_selected_for_browser_automation_carries_gateway_required():
    result = select_provider_for_task(TaskClass.BROWSER_AUTOMATION)
    assert result.selected_provider_id == "twin"
    assert result.gateway_required is True


def test_twin_authority_ceiling_is_bounded_workspace_mutation():
    twin = PROVIDER_REGISTRY["twin"]
    assert twin.authority_ceiling == "bounded_workspace_mutation"


def test_twin_notes_mention_security_gateway():
    twin = PROVIDER_REGISTRY["twin"]
    assert "Security Gateway" in twin.notes or "gateway" in twin.notes.lower()


def test_twin_notes_mention_no_second_control_plane():
    twin = PROVIDER_REGISTRY["twin"]
    assert "control plane" in twin.notes.lower()


# ---------------------------------------------------------------------------
# AC-4: Unavailable/no-API provider represented honestly
# ---------------------------------------------------------------------------


def test_magai_api_not_available():
    magai = PROVIDER_REGISTRY["magai"]
    assert magai.api_availability == ApiAvailability.NOT_AVAILABLE


def test_magai_is_available_false():
    magai = PROVIDER_REGISTRY["magai"]
    assert magai.is_available is False


def test_magai_health_is_unavailable():
    magai = PROVIDER_REGISTRY["magai"]
    assert magai.health == ProviderHealth.UNAVAILABLE


def test_magai_has_no_task_classes():
    magai = PROVIDER_REGISTRY["magai"]
    assert len(magai.task_classes) == 0


def test_magai_authority_ceiling_is_none():
    magai = PROVIDER_REGISTRY["magai"]
    assert magai.authority_ceiling == "none"


def test_magai_notes_mention_not_available():
    magai = PROVIDER_REGISTRY["magai"]
    note = magai.notes.lower()
    assert "not_available" in note or "no integration" in note


def test_scientific_reasoning_returns_no_provider():
    result = select_provider_for_task(TaskClass.SCIENTIFIC_REASONING)
    assert result.selected_provider_id is None


# ---------------------------------------------------------------------------
# AC-5: Subscription-vs-API billing state is explicit
# ---------------------------------------------------------------------------


def test_perplexity_billing_explicitly_separate():
    perp = PROVIDER_REGISTRY["perplexity"]
    assert perp.api_availability == ApiAvailability.SEPARATE_BILLING
    assert "SEPARATE" in perp.subscription_vs_api_billing.upper()


def test_kimi_billing_note_mentions_developer_keys():
    kimi = PROVIDER_REGISTRY["kimi"]
    assert "developer" in kimi.subscription_vs_api_billing.lower()


def test_magai_billing_note_mentions_no_api():
    magai = PROVIDER_REGISTRY["magai"]
    assert "no api" in magai.subscription_vs_api_billing.lower() or (
        "does not offer" in magai.subscription_vs_api_billing.lower()
    )


def test_twin_billing_note_is_explicit_about_unknown():
    twin = PROVIDER_REGISTRY["twin"]
    assert "UNKNOWN" in twin.subscription_vs_api_billing


# ---------------------------------------------------------------------------
# AC-6: Provider selection is deterministic from task class + health
# ---------------------------------------------------------------------------


def test_selection_is_deterministic_same_input_same_result():
    r1 = select_provider_for_task(TaskClass.CODING_REPOSITORY_EDIT)
    r2 = select_provider_for_task(TaskClass.CODING_REPOSITORY_EDIT)
    assert r1.selected_provider_id == r2.selected_provider_id
    assert r1.reason == r2.reason


def test_health_override_unavailable_yields_no_provider():
    result = select_provider_for_task(
        TaskClass.CODING_REPOSITORY_EDIT,
        health_overrides={"kimi": ProviderHealth.UNAVAILABLE},
    )
    assert result.selected_provider_id is None


def test_health_override_healthy_picks_provider():
    result = select_provider_for_task(
        TaskClass.CODING_REPOSITORY_EDIT,
        health_overrides={"kimi": ProviderHealth.HEALTHY},
    )
    assert result.selected_provider_id == "kimi"
    assert result.health == ProviderHealth.HEALTHY


def test_string_task_class_resolved():
    result = select_provider_for_task("coding_repository_edit")
    assert result.selected_provider_id == "kimi"


def test_unknown_task_class_string_returns_none():
    result = select_provider_for_task("totally_unknown_class")
    assert result.selected_provider_id is None


# ---------------------------------------------------------------------------
# AC-7: Missing cost metadata is UNKNOWN, never zero
# ---------------------------------------------------------------------------


def test_all_providers_cost_per_unit_is_unknown():
    for pid, profile in PROVIDER_REGISTRY.items():
        assert profile.cost_per_unit == "UNKNOWN", (
            f"{pid} cost_per_unit should be UNKNOWN; got {profile.cost_per_unit!r}"
        )


def test_selection_result_cost_per_unit_unknown_when_selected():
    result = select_provider_for_task(TaskClass.CODING_REPOSITORY_EDIT)
    assert result.cost_per_unit == "UNKNOWN"


def test_selection_result_cost_per_unit_unknown_when_no_provider():
    result = select_provider_for_task(TaskClass.SCIENTIFIC_REASONING)
    assert result.cost_per_unit == "UNKNOWN"


def test_cost_not_zero_in_report():
    report = build_provider_readiness_report()
    for entry in report["providers"]:
        assert entry["cost_per_unit"] != 0
        assert entry["cost_per_unit"] != "0"


# ---------------------------------------------------------------------------
# AC-8: Fallback/tiering does not alter acceptance gates
# ---------------------------------------------------------------------------


def test_acceptance_gates_unchanged_always_true_on_success():
    result = select_provider_for_task(TaskClass.CODING_REPOSITORY_EDIT)
    assert result.acceptance_gates_unchanged is True


def test_acceptance_gates_unchanged_always_true_on_no_provider():
    result = select_provider_for_task(TaskClass.SCIENTIFIC_REASONING)
    assert result.acceptance_gates_unchanged is True


def test_health_override_no_provider_still_gates_unchanged():
    result = select_provider_for_task(
        TaskClass.CODING_REPOSITORY_EDIT,
        health_overrides={"kimi": ProviderHealth.UNAVAILABLE},
    )
    assert result.acceptance_gates_unchanged is True


# ---------------------------------------------------------------------------
# Mission Control readiness report
# ---------------------------------------------------------------------------


def test_readiness_report_schema_version():
    report = build_provider_readiness_report()
    assert report["schema_version"] == SCHEMA_VERSION


def test_readiness_report_no_secrets():
    report = build_provider_readiness_report()
    serialized = json.dumps(report)
    for bad in ("sk-", "Bearer ", "api_key", "API_KEY"):
        assert bad not in serialized


def test_readiness_report_graph_mutation_false():
    report = build_provider_readiness_report()
    assert report["graph_mutation"] is False


def test_readiness_report_secrets_emitted_false():
    report = build_provider_readiness_report()
    assert report["secrets_emitted"] is False


def test_readiness_report_contains_all_providers():
    report = build_provider_readiness_report()
    ids = {e["provider_id"] for e in report["providers"]}
    assert ids >= {"kimi", "perplexity", "twin", "magai"}


def test_readiness_report_health_override_reflected():
    report = build_provider_readiness_report(
        health_overrides={"kimi": ProviderHealth.HEALTHY}
    )
    kimi_entry = next(e for e in report["providers"] if e["provider_id"] == "kimi")
    assert kimi_entry["health"] == "healthy"


def test_readiness_report_magai_not_available():
    report = build_provider_readiness_report()
    magai_entry = next(e for e in report["providers"] if e["provider_id"] == "magai")
    assert magai_entry["is_available"] is False
    assert magai_entry["health"] == "unavailable"


def test_readiness_report_serializable_as_json():
    report = build_provider_readiness_report()
    output = json.dumps(report)
    parsed = json.loads(output)
    assert parsed["provider_count"] == len(PROVIDER_REGISTRY)


# ---------------------------------------------------------------------------
# to_dict round-trips
# ---------------------------------------------------------------------------


def test_provider_profile_to_dict_contains_expected_keys():
    kimi = PROVIDER_REGISTRY["kimi"]
    d = kimi.to_dict()
    required_keys = {
        "provider_id", "display_name", "task_classes", "api_availability",
        "subscription_vs_api_billing", "cost_per_unit", "authority_ceiling",
        "health", "notes", "gateway_required", "evidence_status", "is_available",
    }
    assert required_keys <= set(d)


def test_selection_result_to_dict_keys():
    result = select_provider_for_task(TaskClass.BROWSER_AUTOMATION)
    d = result.to_dict()
    required_keys = {
        "task_class", "selected_provider_id", "reason", "authority_ceiling",
        "gateway_required", "evidence_status", "cost_per_unit", "health",
        "acceptance_gates_unchanged",
    }
    assert required_keys <= set(d)


def test_selection_result_to_dict_no_none_for_task_class():
    result = select_provider_for_task(TaskClass.RESEARCH_WEB_RETRIEVAL)
    d = result.to_dict()
    assert d["task_class"] == "research_web_retrieval"
