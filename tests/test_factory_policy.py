from __future__ import annotations

import pytest

from app.calyx_orchestrator.factory_policy import (
    CheckerVerdict,
    FactoryAction,
    MissionState,
    MissionStatus,
    RiskTier,
    ValidationEvidence,
    WorkIntent,
    evaluate_factory_gate,
)


def _intent(**overrides: object) -> WorkIntent:
    values: dict[str, object] = {
        "repository": "jsp1440/orchid-calyx-backend",
        "issue_number": 1023,
        "head_sha": "abc123",
        "target_branch": "oc-autonomous-integration",
        "risk_tier": RiskTier.LOW,
        "reversible": True,
    }
    values.update(overrides)
    return WorkIntent(**values)  # type: ignore[arg-type]


def _passing_evidence(**overrides: object) -> ValidationEvidence:
    values: dict[str, object] = {
        "maker_id": "maker-a",
        "checker_id": "checker-b",
        "checker_verdict": CheckerVerdict.PASS,
        "exact_head_verified": True,
        "required_checks_passed": True,
    }
    values.update(overrides)
    return ValidationEvidence(**values)  # type: ignore[arg-type]


def test_safe_non_main_change_can_auto_integrate_after_independent_check() -> None:
    decision = evaluate_factory_gate(_intent(), _passing_evidence())

    assert decision.action is FactoryAction.AUTO_INTEGRATE
    assert decision.integration_authorized is True
    assert decision.reason == "INDEPENDENT_VALIDATION_PASSED_SAFE_INTEGRATION"
    assert len(decision.fingerprint) == 64


def test_maker_cannot_serve_as_checker() -> None:
    evidence = _passing_evidence(checker_id="maker-a")

    decision = evaluate_factory_gate(_intent(), evidence)

    assert decision.action is FactoryAction.REQUIRE_CHECKER
    assert decision.reason == "INDEPENDENT_CHECKER_REQUIRED"
    assert decision.integration_authorized is False


def test_checker_failure_routes_to_repair_not_owner() -> None:
    evidence = _passing_evidence(checker_verdict=CheckerVerdict.FAIL)

    decision = evaluate_factory_gate(_intent(), evidence)

    assert decision.action is FactoryAction.PREPARE_REPAIR
    assert decision.reason == "CHECKER_REJECTED_CHANGE"


@pytest.mark.parametrize(
    "overrides",
    [
        {"target_branch": "main"},
        {"touches_production": True},
        {"changes_credentials": True},
        {"changes_scientific_authority": True},
        {"exposes_sensitive_locality": True},
        {"spends_money": True},
        {"destructive": True},
        {"reversible": False},
    ],
)
def test_owner_boundaries_never_auto_integrate(overrides: dict[str, object]) -> None:
    decision = evaluate_factory_gate(_intent(**overrides), _passing_evidence())

    assert decision.action is FactoryAction.OWNER_GATE
    assert decision.integration_authorized is False


def test_provider_required_work_parks_in_no_api_mode() -> None:
    decision = evaluate_factory_gate(
        _intent(provider_required=True), _passing_evidence(), no_api_mode=True
    )

    assert decision.action is FactoryAction.PARK_PROVIDER_REQUIRED
    assert decision.reason == "NO_API_PROVIDER_WORK_PARKED"


def test_exact_head_and_required_checks_are_mandatory() -> None:
    stale = evaluate_factory_gate(
        _intent(), _passing_evidence(exact_head_verified=False)
    )
    unproven = evaluate_factory_gate(
        _intent(), _passing_evidence(required_checks_passed=False)
    )

    assert stale.action is FactoryAction.REQUIRE_CHECKER
    assert stale.reason == "EXACT_HEAD_VALIDATION_REQUIRED"
    assert unproven.action is FactoryAction.REQUIRE_CHECKER
    assert unproven.reason == "REQUIRED_CHECKS_NOT_PROVEN"


@pytest.mark.parametrize("risk", [RiskTier.HIGH, RiskTier.OWNER_GATED])
def test_high_risk_remains_owner_gated_after_checker_pass(risk: RiskTier) -> None:
    decision = evaluate_factory_gate(_intent(risk_tier=risk), _passing_evidence())

    assert decision.action is FactoryAction.OWNER_GATE
    assert decision.integration_authorized is False


def test_mission_state_is_machine_readable_and_validated() -> None:
    intent = _intent()
    state = MissionState(
        mission_id="OC-1023",
        issue_number=intent.issue_number,
        status=MissionStatus.VALIDATING,
        fingerprint=intent.material_fingerprint,
        attempt_count=1,
        maker_id="maker-a",
        checker_id="checker-b",
        last_reason="CHECKER_PENDING",
    )

    assert state.status is MissionStatus.VALIDATING
    assert state.fingerprint == intent.material_fingerprint


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"mission_id": ""}, "MISSION_ID_REQUIRED"),
        ({"issue_number": 0}, "ISSUE_NUMBER_INVALID"),
        ({"attempt_count": -1}, "ATTEMPT_COUNT_INVALID"),
        ({"fingerprint": ""}, "FINGERPRINT_REQUIRED"),
    ],
)
def test_invalid_mission_state_fails_closed(
    kwargs: dict[str, object], error: str
) -> None:
    values: dict[str, object] = {
        "mission_id": "OC-1023",
        "issue_number": 1023,
        "status": MissionStatus.QUEUED,
        "fingerprint": "abc",
        "attempt_count": 0,
    }
    values.update(kwargs)
    with pytest.raises(ValueError, match=error):
        MissionState(**values)  # type: ignore[arg-type]
