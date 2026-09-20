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
        "head_sha": "6a57183395c29f0a47b4a11cd86fabe34ac10d95",
        "target_branch": "oc-autonomous-integration",
        "risk_tier": RiskTier.LOW,
        "reversible": True,
    }
    values.update(overrides)
    return WorkIntent(**values)  # type: ignore[arg-type]


#: Two real commits from this repository's merge-verifier lineage, used here
#: only as "this head" and "some other head". The comment that stood here said
#: #1524 "was merged at the first while its review was at the second"; #1524
#: was merged at `657b2f1`, which is the SECOND, and `6a57183` is the commit
#: that carried what the review of #1526's head found, forty minutes after
#: #1526 had merged. Both halves were wrong, in a file about evidence naming
#: the wrong commit.
HEAD = "6a57183395c29f0a47b4a11cd86fabe34ac10d95"
OTHER_HEAD = "657b2f183c35852af10ca290730b03a23dd1d64e"


def _passing_evidence(**overrides: object) -> ValidationEvidence:
    values: dict[str, object] = {
        "maker_id": "maker-a",
        "checker_id": "checker-b",
        "checker_verdict": CheckerVerdict.PASS,
        "required_checks_passed": True,
        # `exact_head_verified` is derived, not asserted: the three heads are
        # recorded and the gate compares them. Passing evidence is evidence in
        # which all three name the same commit.
        "head_sha": HEAD,
        "checker_head_sha": HEAD,
        "checks_head_sha": HEAD,
    }
    values.update(overrides)
    return ValidationEvidence(**values)  # type: ignore[arg-type]


def test_safe_non_main_change_can_auto_integrate_after_independent_check() -> None:
    decision = evaluate_factory_gate(_intent(), _passing_evidence())

    assert decision.action is FactoryAction.AUTO_INTEGRATE
    assert decision.integration_authorized is True
    assert decision.reason == "INDEPENDENT_VALIDATION_PASSED_SAFE_INTEGRATION"
    assert len(decision.fingerprint) == 64


def test_evidence_for_another_head_cannot_authorize_at_the_gate_itself() -> None:
    decision = evaluate_factory_gate(
        _intent(head_sha=OTHER_HEAD),
        _passing_evidence(head_sha=HEAD, checker_head_sha=HEAD, checks_head_sha=HEAD),
    )

    assert decision.action is FactoryAction.REQUIRE_CHECKER
    assert decision.reason.startswith("INTENT_HEAD_MISMATCH")
    # And it names both commits. A refusal that cannot say which commit it is
    # about is the defect this lineage replaced `EXACT_HEAD_VALIDATION_REQUIRED`
    # to fix; a gate added later should not reintroduce it one line down.
    assert OTHER_HEAD[:12] in decision.reason
    assert HEAD[:12] in decision.reason
    assert decision.integration_authorized is False


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
        _intent(), _passing_evidence(checker_head_sha=OTHER_HEAD)
    )
    unproven = evaluate_factory_gate(
        _intent(), _passing_evidence(required_checks_passed=False)
    )

    assert stale.action is FactoryAction.REQUIRE_CHECKER
    # The refusal names the commit the evidence was actually about. The old
    # message said only that validation was "required", which reads as "nobody
    # checked" when the truth is "somebody checked something else".
    assert stale.reason.startswith("EVIDENCE_IS_ABOUT_ANOTHER_HEAD")
    assert OTHER_HEAD[:12] in stale.reason
    assert unproven.action is FactoryAction.REQUIRE_CHECKER
    assert unproven.reason == "REQUIRED_CHECKS_NOT_PROVEN"


def test_an_unrecorded_head_is_never_verification() -> None:
    # Absence is not agreement. A record that cannot say which commit it is
    # about must not satisfy a check named "exact head".
    for missing in (
        {"head_sha": ""},
        {"checker_head_sha": ""},
        {"checks_head_sha": ""},
    ):
        decision = evaluate_factory_gate(_intent(), _passing_evidence(**missing))
        assert decision.action is FactoryAction.REQUIRE_CHECKER
        assert decision.integration_authorized is False


def test_an_abbreviated_head_is_not_a_head() -> None:
    # Two commits can share a prefix, so a 12-hex "head" is a string that could
    # name something else later.
    decision = evaluate_factory_gate(
        _intent(),
        _passing_evidence(
            head_sha=HEAD[:12], checker_head_sha=HEAD[:12], checks_head_sha=HEAD[:12]
        ),
    )

    assert decision.action is FactoryAction.REQUIRE_CHECKER
    assert decision.integration_authorized is False


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


# ---------------------------------------------------------------------------
# The live gate, not the module beside it. An independent check degraded this
# property to a 7-hex AND a 12-hex prefix comparison with the whole suite green,
# because the prefix test had been written against `head_bound_integration` --
# and this is the copy the merge path actually reads.
# ---------------------------------------------------------------------------


#: Two SYNTHETIC ids sharing a 12-hex prefix. Synthetic on purpose -- the point
#: is the comparison, and two real commits colliding on twelve hex would have to
#: be manufactured anyway. The comment here called them "two real commits",
#: which they are not: `git rev-parse --verify abc1234def56` resolves nothing.
PREFIX_A = "abc1234def56" + "0" * 28
PREFIX_B = "abc1234def56" + "f" * 28


def test_two_heads_sharing_a_twelve_hex_prefix_are_different_heads() -> None:
    assert PREFIX_A != PREFIX_B
    assert PREFIX_A[:12] == PREFIX_B[:12]

    decision = evaluate_factory_gate(
        _intent(),
        _passing_evidence(
            head_sha=PREFIX_A, checker_head_sha=PREFIX_B, checks_head_sha=PREFIX_A
        ),
    )

    assert decision.integration_authorized is False
    assert decision.action is FactoryAction.REQUIRE_CHECKER


def test_and_the_same_holds_for_the_checks_head() -> None:
    decision = evaluate_factory_gate(
        _intent(),
        _passing_evidence(
            head_sha=PREFIX_A, checker_head_sha=PREFIX_A, checks_head_sha=PREFIX_B
        ),
    )

    assert decision.integration_authorized is False


def test_a_head_differing_only_in_case_is_a_different_head() -> None:
    # An actor id is a label; a commit id is not. Case folding here would make
    # evidence about one object authorize another.
    decision = evaluate_factory_gate(
        _intent(), _passing_evidence(checker_head_sha=HEAD.upper())
    )

    assert decision.integration_authorized is False


def test_a_head_with_a_trailing_newline_is_not_a_head() -> None:
    # `$` matches before a trailing newline, so `re.match` accepted this --
    # which is exactly what a head read from an unstripped capture looks like.
    # The rule now lives in one place, `head_bound_integration._FULL_SHA`, and
    # is enforced by refusing to CONSTRUCT the observation; this asserts the
    # gate reached through that path rather than around it.
    newline_head = HEAD + "\n"
    decision = evaluate_factory_gate(
        _intent(),
        _passing_evidence(
            head_sha=newline_head,
            checker_head_sha=newline_head,
            checks_head_sha=newline_head,
        ),
    )

    assert decision.integration_authorized is False


def test_a_maker_cannot_be_their_own_checker_by_adding_a_space() -> None:
    # `independent_checker` compared raw strings, so "maker-a " reviewed
    # "maker-a"'s own work.
    for spelling in ("maker-a ", " maker-a", "MAKER-A", "maker-a\n", "  "):
        decision = evaluate_factory_gate(
            _intent(), _passing_evidence(checker_id=spelling)
        )
        assert decision.integration_authorized is False, spelling


class TestTheIdentityPropertyItself:
    """The gate test above passes whatever `independent_checker` does.

    Both refusals fire on a self-review -- the delegated head-bound rule and
    this property -- so degrading the property to raw string equality left the
    gate refusing anyway and the mutant survived. A rule that two guards both
    cover is only tested where it is asked directly.
    """

    def test_respellings_of_the_maker_are_the_maker(self) -> None:
        for spelling in ("maker-a ", " maker-a", "MAKER-A", "maker-a\n", "Maker-A"):
            evidence = _passing_evidence(checker_id=spelling)
            assert evidence.independent_checker is False, spelling

    def test_a_genuinely_different_checker_is_independent(self) -> None:
        assert _passing_evidence(checker_id="checker-b").independent_checker is True

    def test_an_absent_checker_is_not_an_independent_one(self) -> None:
        # `None` is the commonest of these -- it is what a record says before
        # anyone has checked -- and it must read as a no, not raise inside the
        # gate. The first attempt at the `strip()` fix did exactly that.
        for spelling in ("", "   ", "\n", None):
            evidence = _passing_evidence(checker_id=spelling)
            assert evidence.independent_checker is False, repr(spelling)
