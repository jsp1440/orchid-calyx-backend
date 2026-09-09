from __future__ import annotations

import pytest

from app.calyx_orchestrator.checker_dispatch import (
    CHECKER_ASSIGNMENT_TAG,
    CHECKER_EVIDENCE_TAG,
    CheckerAssignment,
    CheckerDispatchError,
    CheckerEvidence,
    assign_checker,
    evidence_to_validation,
    parse_assignment,
    parse_evidence,
    serialize_assignment,
    serialize_evidence,
    validate_checker_evidence,
)
from app.calyx_orchestrator.factory_policy import (
    CheckerVerdict,
    FactoryAction,
    RiskTier,
    ValidationEvidence,
    WorkIntent,
    evaluate_factory_gate,
)

REPO = "jsp1440/orchid-calyx-backend"
MAKER = "maker-agent-a"
CHECKER = "checker-agent-b"
HEAD_SHA = "d71452d069c66015211df5cbf385163e7da1e1c1"
PR_NUMBER = 1297
ISSUE_NUMBER = 1023


def _intent(**overrides: object) -> WorkIntent:
    values: dict[str, object] = {
        "repository": REPO,
        "issue_number": ISSUE_NUMBER,
        "head_sha": HEAD_SHA,
        "target_branch": "oc-autonomous-integration",
        "risk_tier": RiskTier.LOW,
        "reversible": True,
    }
    values.update(overrides)
    return WorkIntent(**values)  # type: ignore[arg-type]


def _assignment(**overrides: object) -> CheckerAssignment:
    intent = _intent()
    values: dict[str, object] = {
        "repository": REPO,
        "issue_number": ISSUE_NUMBER,
        "pr_number": PR_NUMBER,
        "head_sha": HEAD_SHA,
        "maker_id": MAKER,
        "checker_id": CHECKER,
        "material_fingerprint": intent.material_fingerprint,
    }
    values.update(overrides)
    return CheckerAssignment(**values)  # type: ignore[arg-type]


def _evidence(**overrides: object) -> CheckerEvidence:
    intent = _intent()
    values: dict[str, object] = {
        "repository": REPO,
        "issue_number": ISSUE_NUMBER,
        "pr_number": PR_NUMBER,
        "checked_head_sha": HEAD_SHA,
        "checker_id": CHECKER,
        "maker_id": MAKER,
        "verdict": CheckerVerdict.PASS,
        "required_checks_passed": True,
        "reason": "All checks green on exact head.",
        "material_fingerprint": intent.material_fingerprint,
    }
    values.update(overrides)
    return CheckerEvidence(**values)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Invariant 1: maker cannot be checker
# ---------------------------------------------------------------------------


def test_maker_cannot_be_assigned_as_checker() -> None:
    with pytest.raises(ValueError, match="CHECKER_MUST_DIFFER_FROM_MAKER"):
        _assignment(checker_id=MAKER)


def test_assign_checker_raises_when_only_maker_available() -> None:
    intent = _intent()
    with pytest.raises(CheckerDispatchError, match="NO_INDEPENDENT_CHECKER_AVAILABLE"):
        assign_checker(intent, PR_NUMBER, MAKER, available_checkers=[MAKER])


def test_assign_checker_skips_maker_and_selects_independent() -> None:
    intent = _intent()
    assignment = assign_checker(
        intent, PR_NUMBER, MAKER, available_checkers=[MAKER, CHECKER]
    )
    assert assignment.checker_id == CHECKER
    assert assignment.maker_id == MAKER
    assert assignment.checker_id != assignment.maker_id


def test_checker_evidence_cannot_have_checker_equal_maker() -> None:
    with pytest.raises(ValueError, match="CHECKER_MUST_DIFFER_FROM_MAKER"):
        _evidence(checker_id=MAKER)


# ---------------------------------------------------------------------------
# Invariant 2: missing checker cannot authorize integration
# ---------------------------------------------------------------------------


def test_missing_checker_id_in_evidence_fails_validation() -> None:
    assignment = _assignment()
    evidence = _evidence(checker_id="other-agent")  # does not match assignment
    errors = validate_checker_evidence(assignment, evidence)
    assert any("CHECKER_ID_MISMATCH" in e for e in errors)


def test_pending_validation_evidence_does_not_authorize_integration() -> None:
    pending = ValidationEvidence(maker_id=MAKER)
    decision = evaluate_factory_gate(_intent(), pending)
    assert decision.action is FactoryAction.REQUIRE_CHECKER
    assert decision.integration_authorized is False


# ---------------------------------------------------------------------------
# Invariant 3: checker approval for SHA A cannot authorize changed SHA B
# ---------------------------------------------------------------------------


def test_evidence_for_different_sha_fails_validation() -> None:
    assignment = _assignment(head_sha=HEAD_SHA)
    evidence = _evidence(checked_head_sha="0000000000000000000000000000000000000000")
    errors = validate_checker_evidence(assignment, evidence)
    assert any("HEAD_SHA_MISMATCH" in e for e in errors)


def test_evidence_to_validation_raises_on_sha_mismatch() -> None:
    assignment = _assignment(head_sha=HEAD_SHA)
    evidence = _evidence(checked_head_sha="different-sha-entirely-not-matching-head")
    with pytest.raises(CheckerDispatchError, match="INVALID_CHECKER_EVIDENCE"):
        evidence_to_validation(assignment, evidence)


def test_stale_sha_evidence_does_not_reach_auto_integrate() -> None:
    intent_sha_a = _intent(head_sha=HEAD_SHA)
    assignment = assign_checker(intent_sha_a, PR_NUMBER, MAKER, [CHECKER])

    # Evidence references a different (newer) SHA
    stale_evidence = _evidence(checked_head_sha="newsha-that-does-not-match-original")
    errors = validate_checker_evidence(assignment, stale_evidence)
    assert errors  # must not be empty


# ---------------------------------------------------------------------------
# Invariant 4: malformed/incomplete evidence fails closed
# ---------------------------------------------------------------------------


def test_parse_assignment_returns_none_for_missing_tag() -> None:
    assert parse_assignment("This comment has no structured data.") is None


def test_parse_assignment_returns_none_for_malformed_json() -> None:
    body = f"<!-- {CHECKER_ASSIGNMENT_TAG}\n{{not: valid json}}\n-->"
    assert parse_assignment(body) is None


def test_parse_evidence_returns_none_for_missing_tag() -> None:
    assert parse_evidence("No evidence here.") is None


def test_parse_evidence_returns_none_for_malformed_json() -> None:
    body = f"<!-- {CHECKER_EVIDENCE_TAG}\n{{broken\n-->"
    assert parse_evidence(body) is None


def test_parse_evidence_returns_none_for_missing_required_field() -> None:
    import json

    payload = {
        "tag": CHECKER_EVIDENCE_TAG,
        "repository": REPO,
        # issue_number intentionally omitted
        "pr_number": PR_NUMBER,
        "checked_head_sha": HEAD_SHA,
        "checker_id": CHECKER,
        "maker_id": MAKER,
        "verdict": "pass",
        "required_checks_passed": True,
        "reason": "ok",
        "material_fingerprint": _intent().material_fingerprint,
    }
    body = f"<!-- {CHECKER_EVIDENCE_TAG}\n{json.dumps(payload)}\n-->"
    assert parse_evidence(body) is None


def test_evidence_with_unknown_verdict_fails_closed() -> None:
    import json

    payload = {
        "tag": CHECKER_EVIDENCE_TAG,
        "repository": REPO,
        "issue_number": ISSUE_NUMBER,
        "pr_number": PR_NUMBER,
        "checked_head_sha": HEAD_SHA,
        "checker_id": CHECKER,
        "maker_id": MAKER,
        "verdict": "UNKNOWN_VERDICT",
        "required_checks_passed": True,
        "reason": "ok",
        "material_fingerprint": _intent().material_fingerprint,
        "repair_lineage": None,
    }
    body = f"<!-- {CHECKER_EVIDENCE_TAG}\n{json.dumps(payload)}\n-->"
    assert parse_evidence(body) is None


# ---------------------------------------------------------------------------
# Invariant 5: checker FAIL routes to bounded repair
# ---------------------------------------------------------------------------


def test_checker_fail_evidence_routes_to_prepare_repair() -> None:
    assignment = _assignment()
    evidence = _evidence(verdict=CheckerVerdict.FAIL)
    validation = evidence_to_validation(assignment, evidence)

    decision = evaluate_factory_gate(_intent(), validation)

    assert decision.action is FactoryAction.PREPARE_REPAIR
    assert decision.reason == "CHECKER_REJECTED_CHANGE"
    assert decision.integration_authorized is False


def test_checker_fail_with_repair_lineage_is_recorded() -> None:
    ev = _evidence(verdict=CheckerVerdict.FAIL, repair_lineage="abc123-repair-attempt-1")
    assert ev.verdict is CheckerVerdict.FAIL
    assert ev.repair_lineage == "abc123-repair-attempt-1"


# ---------------------------------------------------------------------------
# Invariant 6: checker INCONCLUSIVE does not integrate
# ---------------------------------------------------------------------------


def test_checker_inconclusive_does_not_authorize_integration() -> None:
    assignment = _assignment()
    evidence = _evidence(verdict=CheckerVerdict.INCONCLUSIVE)
    validation = evidence_to_validation(assignment, evidence)

    decision = evaluate_factory_gate(_intent(), validation)

    assert decision.action is FactoryAction.REQUIRE_CHECKER
    assert decision.integration_authorized is False


# ---------------------------------------------------------------------------
# Invariant 7: checker PASS + exact-head + required checks → AUTO_INTEGRATE
# ---------------------------------------------------------------------------


def test_valid_checker_pass_reaches_auto_integrate_for_safe_work() -> None:
    intent = _intent()
    assignment = assign_checker(intent, PR_NUMBER, MAKER, [CHECKER])
    evidence = _evidence()

    # No mismatches
    assert validate_checker_evidence(assignment, evidence) == []

    validation = evidence_to_validation(assignment, evidence)

    assert validation.checker_id == CHECKER
    assert validation.exact_head_verified is True
    assert validation.required_checks_passed is True

    decision = evaluate_factory_gate(intent, validation)

    assert decision.action is FactoryAction.AUTO_INTEGRATE
    assert decision.integration_authorized is True


# ---------------------------------------------------------------------------
# Invariant 8: replayed/duplicate checker evidence does not create duplicate state
# ---------------------------------------------------------------------------


def test_serialized_assignment_round_trips_exactly() -> None:
    assignment = _assignment()
    body = serialize_assignment(assignment)
    recovered = parse_assignment(body)

    assert recovered is not None
    assert recovered == assignment


def test_serialized_evidence_round_trips_exactly() -> None:
    evidence = _evidence(repair_lineage="prior-attempt-sha")
    body = serialize_evidence(evidence)
    recovered = parse_evidence(body)

    assert recovered is not None
    assert recovered == evidence


def test_duplicate_evidence_record_parses_to_same_object() -> None:
    evidence = _evidence()
    body = serialize_evidence(evidence)

    first = parse_evidence(body)
    second = parse_evidence(body)

    assert first == second  # same content, same fingerprint → idempotent re-evaluation


def test_replayed_evidence_produces_same_factory_decision() -> None:
    assignment = _assignment()
    evidence = _evidence()
    validation = evidence_to_validation(assignment, evidence)

    d1 = evaluate_factory_gate(_intent(), validation)
    d2 = evaluate_factory_gate(_intent(), validation)

    assert d1 == d2
    assert d1.action is FactoryAction.AUTO_INTEGRATE


# ---------------------------------------------------------------------------
# Invariant 9: high-risk/owner-gated work remains owner-gated after checker PASS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("risk", [RiskTier.HIGH, RiskTier.OWNER_GATED])
def test_high_risk_remains_owner_gated_even_after_checker_pass(risk: RiskTier) -> None:
    assignment = _assignment()
    evidence = _evidence()
    validation = evidence_to_validation(assignment, evidence)

    decision = evaluate_factory_gate(_intent(risk_tier=risk), validation)

    assert decision.action is FactoryAction.OWNER_GATE
    assert decision.integration_authorized is False


@pytest.mark.parametrize(
    "override",
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
def test_owner_boundaries_remain_gated_after_checker_pass(
    override: dict[str, object],
) -> None:
    assignment = _assignment()
    evidence = _evidence()
    validation = evidence_to_validation(assignment, evidence)

    decision = evaluate_factory_gate(_intent(**override), validation)

    assert decision.action is FactoryAction.OWNER_GATE
    assert decision.integration_authorized is False


# ---------------------------------------------------------------------------
# assign_checker edge cases
# ---------------------------------------------------------------------------


def test_assign_checker_raises_when_no_checkers() -> None:
    with pytest.raises(CheckerDispatchError, match="NO_CHECKERS_AVAILABLE"):
        assign_checker(_intent(), PR_NUMBER, MAKER, available_checkers=[])


def test_assign_checker_selects_first_independent() -> None:
    intent = _intent()
    assignment = assign_checker(
        intent, PR_NUMBER, MAKER, [MAKER, "skipped", CHECKER, "also-valid"]
    )
    assert assignment.checker_id == "skipped"


def test_assignment_binds_exact_head_sha() -> None:
    intent = _intent(head_sha="exact-sha-abcdef123456")
    assignment = assign_checker(intent, PR_NUMBER, MAKER, [CHECKER])
    assert assignment.head_sha == "exact-sha-abcdef123456"


def test_assignment_binds_material_fingerprint() -> None:
    intent = _intent()
    assignment = assign_checker(intent, PR_NUMBER, MAKER, [CHECKER])
    assert assignment.material_fingerprint == intent.material_fingerprint


# ---------------------------------------------------------------------------
# validate_checker_evidence: multi-field mismatches all reported
# ---------------------------------------------------------------------------


def test_validate_reports_all_mismatches_not_just_first() -> None:
    assignment = _assignment()
    evidence = _evidence(
        repository="jsp1440/other-repo",
        issue_number=9999,
        checked_head_sha="wrong-sha",
    )
    errors = validate_checker_evidence(assignment, evidence)
    assert len(errors) >= 3
    reasons = " ".join(errors)
    assert "REPOSITORY_MISMATCH" in reasons
    assert "ISSUE_NUMBER_MISMATCH" in reasons
    assert "HEAD_SHA_MISMATCH" in reasons
