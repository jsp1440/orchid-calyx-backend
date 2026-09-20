"""The three merges that motivated this, and the rule that refuses them.

Every SHA below is real, and every claim about it is checkable against the
repository and the GitHub API. An earlier version of this docstring was not:
it paired #1526 with `9acced7`, which is #1530's merged head, and called
`6a57183` "#1524's review", which it is not. A file about evidence naming the
wrong commit had named the wrong commits.

What actually happened, by the clock:

===== ======================= ========================= =======================
PR    merged at               opened -> merged          the review of THAT head
===== ======================= ========================= =======================
#1524 `657b2f1`               19:12 -> 22:07            returned afterwards; its
                                                        findings became #1526
#1526 `85bb2b2`               23:50 -> 00:06 (16 min)   returned afterwards, at
                                                        `6a57183`, 00:46 -- 40
                                                        minutes past the merge
#1530 `9acced7`               02:40 -> 02:47 (6 min)    never ran
===== ======================= ========================= =======================

In each case the evidence on file was TRUE -- of a commit that was not the one
being merged, or it did not exist yet.
"""

from __future__ import annotations

import re

import pytest

from app.calyx_orchestrator.head_bound_integration import (
    EvidenceSource,
    IntegrationDecision,
    IntegrationEvidence,
    IntegrationStep,
    Observation,
    Refusal,
    decide_next_step,
    exact_head_verified,
    may_integrate,
)

#: Real commits from the lineage this module exists because of. The names say
#: what each commit IS, not what it would be convenient for it to be.
#: The head #1524 merged at.
MERGED_1524 = "657b2f183c35852af10ca290730b03a23dd1d64e"
#: The head #1526 merged at.
MERGED_1526 = "85bb2b2d886a27f207cd3b1ee8d9837f8dfe5f11"
#: The commit carrying what the review of `85bb2b2` found -- pushed 40 minutes
#: after #1526 had already merged that head. Newer than the merged head, real,
#: and about a different commit: the exact shape this module refuses.
FIX_AFTER_1526 = "6a57183395c29f0a47b4a11cd86fabe34ac10d95"
#: The head #1530 merged at, six minutes after it was opened.
MERGED_1530 = "9acced7e703544c701b3730152b56ca558f9d394"

MAKER = "maker:session-a"
CHECKER = "checker:session-b"


def passing(source: EvidenceSource, head: str, observer: str = CHECKER) -> Observation:
    return Observation(source=source, head_sha=head, passed=True, observer_id=observer)


def ready(head: str) -> IntegrationEvidence:
    """A pull request whose checks and review both name the head that would merge."""
    return IntegrationEvidence(
        head_sha=head,
        maker_id=MAKER,
        checks=passing(EvidenceSource.REQUIRED_CHECKS, head, observer="ci"),
        review=passing(EvidenceSource.INDEPENDENT_CHECKER, head),
    )


class TestTheMergesThatMotivatedThis:
    def test_a_review_of_a_later_head_does_not_authorize_the_earlier_one(self):
        """#1524 merged at `657b2f1`. A review naming any other commit --
        here `6a57183` -- authorizes that other commit and not this one."""
        evidence = IntegrationEvidence(
            head_sha=MERGED_1524,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, MERGED_1524, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526),
        )

        decision = decide_next_step(evidence)

        assert decision.may_integrate is False
        assert Refusal.REVIEW_STALE in decision.refusals
        assert decision.blocked_on_stale_evidence is True
        # The refusal names the commit the review was actually about, so an
        # operator can see at a glance that the evidence is real but misfiled.
        assert FIX_AFTER_1526[:12] in decision.reason
        assert decision.step is IntegrationStep.REQUEST_INDEPENDENT_REVIEW

    def test_the_same_holds_however_recent_the_review_is(self):
        """#1526: the review of `85bb2b2` returned at `6a57183`, 40 minutes
        after `85bb2b2` had merged. Newer is not the same as about."""
        evidence = IntegrationEvidence(
            head_sha=MERGED_1526,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, MERGED_1526, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526),
        )

        assert may_integrate(evidence) is False
        assert Refusal.REVIEW_STALE in decide_next_step(evidence).refusals

    def test_no_review_at_all_is_refused_before_anything_else(self):
        """#1530: merged six minutes after it was opened."""
        evidence = IntegrationEvidence(
            head_sha=MERGED_1526,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, MERGED_1526, observer="ci"),
        )

        decision = decide_next_step(evidence)

        assert decision.may_integrate is False
        assert decision.refusals == (Refusal.REVIEW_MISSING,)
        assert decision.step is IntegrationStep.REQUEST_INDEPENDENT_REVIEW

    def test_and_the_same_evidence_authorizes_the_head_it_is_actually_about(self):
        # Nothing here is hostile to the evidence. It is good evidence, about
        # `6a57183`, and it authorizes exactly that commit -- which is the
        # commit it was produced against.
        assert may_integrate(ready(FIX_AFTER_1526)) is True


class TestAHeadThatMovedStartsAgain:
    def test_checks_from_the_previous_head_do_not_carry_forward(self):
        evidence = IntegrationEvidence(
            head_sha=MERGED_1530,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, MERGED_1526, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, MERGED_1530),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.RUN_CHECKS
        assert decision.refusals == (Refusal.CHECKS_STALE,)

    def test_the_earliest_missing_fact_is_the_one_reported(self):
        # Both are stale. Telling the operator to re-review first would send
        # them to redo work that the re-run of checks may change anyway.
        evidence = IntegrationEvidence(
            head_sha=MERGED_1530,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, MERGED_1526, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, MERGED_1526),
        )

        assert decide_next_step(evidence).step is IntegrationStep.RUN_CHECKS
        assert len(evidence.stale()) == 2

    def test_a_passing_review_of_a_failing_head_is_still_about_that_head(self):
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=Observation(
                source=EvidenceSource.REQUIRED_CHECKS,
                head_sha=FIX_AFTER_1526,
                passed=False,
                observer_id="ci",
            ),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.REPAIR
        assert decision.refusals == (Refusal.CHECKS_FAILED,)
        assert decision.blocked_on_stale_evidence is False


class TestEvidenceMustNameItsCommit:
    @pytest.mark.parametrize(
        "head",
        [
            "",
            "   ",
            "657b2f1",  # an abbreviation git would happily resolve
            "657b2f183c35852af10ca290730b03a23dd1d64",  # 39
            "657b2f183c35852af10ca290730b03a23dd1d64ez",
            "657B2F183C35852AF10CA290730B03A23DD1D64E",  # uppercase is a different string
        ],
    )
    def test_an_observation_that_cannot_name_a_commit_cannot_be_constructed(self, head):
        with pytest.raises(ValueError):
            Observation(
                source=EvidenceSource.REQUIRED_CHECKS, head_sha=head, passed=True
            )

    def test_and_neither_can_the_evidence_record(self):
        with pytest.raises(ValueError):
            IntegrationEvidence(head_sha="657b2f1", maker_id=MAKER)

    def test_an_abbreviation_is_refused_rather_than_matched_by_prefix(self):
        # Two commits can share a prefix. "The head I checked" must not be a
        # string that could name something else later.
        with pytest.raises(ValueError):
            Observation(
                source=EvidenceSource.INDEPENDENT_CHECKER,
                head_sha=MERGED_1524[:12],
                passed=True,
            )


class TestTheReviewerIsNotTheMaker:
    def test_a_maker_cannot_certify_their_own_head(self):
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=passing(
                EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
            ),
            review=passing(
                EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526, observer=MAKER
            ),
        )

        decision = decide_next_step(evidence)

        assert decision.may_integrate is False
        assert decision.refusals == (Refusal.REVIEW_NOT_INDEPENDENT,)

    def test_an_anonymous_review_is_not_an_independent_one(self):
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=passing(
                EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
            ),
            review=passing(
                EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526, observer="  "
            ),
        )

        assert decide_next_step(evidence).refusals == (Refusal.REVIEW_NOT_INDEPENDENT,)


class TestTheLoopDoesNotEndAtTheMerge:
    def test_integration_is_followed_by_verifying_what_landed(self):
        decision = decide_next_step(ready(FIX_AFTER_1526))
        assert decision.step is IntegrationStep.INTEGRATE
        assert decision.may_integrate is True

    def test_a_confirmed_landing_retires_the_lease(self):
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=passing(
                EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
            ),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526),
            landed=passing(
                EvidenceSource.LANDED_RESULT, FIX_AFTER_1526, observer="verifier"
            ),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.RETIRE_LEASE
        assert decision.may_integrate is False
        assert decision.refusals == ()

    def test_a_merge_that_did_not_land_the_verified_result_goes_to_repair(self):
        # The #706 failure: the merge API said yes and the tree was wrong.
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=passing(
                EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
            ),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526),
            landed=Observation(
                source=EvidenceSource.LANDED_RESULT,
                head_sha=FIX_AFTER_1526,
                passed=False,
                observer_id="verifier",
            ),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.REPAIR
        assert decision.refusals == (Refusal.LANDED_RESULT_UNVERIFIED,)

    def test_a_landing_check_about_another_head_does_not_close_the_loop(self):
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=passing(
                EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
            ),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526),
            landed=passing(
                EvidenceSource.LANDED_RESULT, MERGED_1524, observer="verifier"
            ),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.VERIFY_LANDED_RESULT
        assert decision.refusals == (Refusal.LANDED_RESULT_STALE,)


class TestExactHeadVerifiedIsDerivedNotAsserted:
    def test_it_is_true_only_when_both_facts_name_this_head_and_pass(self):
        assert exact_head_verified(ready(FIX_AFTER_1526)) is True

    @pytest.mark.parametrize(
        "checks_head,review_head,checks_pass,review_pass",
        [
            (MERGED_1524, FIX_AFTER_1526, True, True),
            (FIX_AFTER_1526, MERGED_1524, True, True),
            (FIX_AFTER_1526, FIX_AFTER_1526, False, True),
            (FIX_AFTER_1526, FIX_AFTER_1526, True, False),
        ],
    )
    def test_and_false_for_every_way_of_being_about_something_else(
        self, checks_head, review_head, checks_pass, review_pass
    ):
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=Observation(
                source=EvidenceSource.REQUIRED_CHECKS,
                head_sha=checks_head,
                passed=checks_pass,
                observer_id="ci",
            ),
            review=Observation(
                source=EvidenceSource.INDEPENDENT_CHECKER,
                head_sha=review_head,
                passed=review_pass,
                observer_id=CHECKER,
            ),
        )

        assert exact_head_verified(evidence) is False

    def test_missing_evidence_is_not_verification(self):
        assert (
            exact_head_verified(
                IntegrationEvidence(head_sha=FIX_AFTER_1526, maker_id=MAKER)
            )
            is False
        )


class TestTheDecisionIsReproducible:
    def test_the_same_record_always_gives_the_same_decision(self):
        evidence = ready(FIX_AFTER_1526)
        first = decide_next_step(evidence)
        second = decide_next_step(evidence)

        assert first == second
        assert isinstance(first, IntegrationDecision)

    def test_stale_lists_every_observation_about_another_commit(self):
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, MERGED_1524, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, MERGED_1526),
            landed=passing(EvidenceSource.LANDED_RESULT, FIX_AFTER_1526, observer="v"),
        )

        stale = evidence.stale()

        assert {observation.source for observation in stale} == {
            EvidenceSource.REQUIRED_CHECKS,
            EvidenceSource.INDEPENDENT_CHECKER,
        }


class TestTheGapsAMutationSweepFound:
    """Three guards that survived the first sweep, and the cases that pin them."""

    def test_two_heads_sharing_a_prefix_are_different_heads(self):
        """`is_about` must compare the whole id.

        Prefix matching survived the first sweep because no fixture had two
        commits sharing one. Git itself resolves a 7-hex prefix, so this is the
        exact shape that makes "the head I checked" name something else later.
        """
        reviewed = "abcdef01" + "1" * 32
        merged = "abcdef01" + "2" * 32
        assert reviewed[:8] == merged[:8]

        evidence = IntegrationEvidence(
            head_sha=merged,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, merged, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, reviewed),
        )

        decision = decide_next_step(evidence)

        assert decision.may_integrate is False
        assert Refusal.REVIEW_STALE in decision.refusals
        assert exact_head_verified(evidence) is False

    def test_no_check_result_at_all_is_refused_before_the_review(self):
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.RUN_CHECKS
        assert decision.refusals == (Refusal.CHECKS_NOT_RUN,)
        assert decision.may_integrate is False

    def test_a_review_that_rejected_this_head_routes_to_repair(self):
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=passing(
                EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
            ),
            review=Observation(
                source=EvidenceSource.INDEPENDENT_CHECKER,
                head_sha=FIX_AFTER_1526,
                passed=False,
                observer_id=CHECKER,
            ),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.REPAIR
        assert decision.refusals == (Refusal.REVIEW_REJECTED,)
        assert decision.may_integrate is False
        # A rejection is about THIS head, so it is not stale evidence.
        assert decision.blocked_on_stale_evidence is False


class TestAnObservationMustReportOnSomething:
    """The module's own first defects: the rule satisfied vacuously.

    Nothing checked that an observation was filed in the slot it belongs to, so
    a check run placed in `review` satisfied "an independent review happened" --
    an observation that names the right commit and reports on nothing. And the
    SAME observation could fill both slots, so one check run counted as the
    checks AND the review.
    """

    def test_a_check_run_filed_as_a_review_is_refused(self):
        with pytest.raises(ValueError, match="WRONG_SLOT"):
            IntegrationEvidence(
                head_sha=FIX_AFTER_1526,
                maker_id=MAKER,
                checks=passing(
                    EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
                ),
                review=passing(EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526),
            )

    def test_a_pull_request_head_reading_is_not_a_check_run(self):
        with pytest.raises(ValueError, match="WRONG_SLOT"):
            IntegrationEvidence(
                head_sha=FIX_AFTER_1526,
                maker_id=MAKER,
                checks=passing(
                    EvidenceSource.PULL_REQUEST, FIX_AFTER_1526, observer="ci"
                ),
            )

    def test_a_landing_check_is_not_a_review(self):
        with pytest.raises(ValueError, match="WRONG_SLOT"):
            IntegrationEvidence(
                head_sha=FIX_AFTER_1526,
                maker_id=MAKER,
                checks=passing(
                    EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
                ),
                review=passing(EvidenceSource.LANDED_RESULT, FIX_AFTER_1526),
            )

    def test_one_observation_cannot_fill_both_slots(self):
        # It used to: a single check run counted as the checks AND the review.
        # The slot rule makes that impossible rather than a separate guard, so
        # there is no guard that cannot fire pretending to be protection.
        one = passing(EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci")

        with pytest.raises(ValueError, match="WRONG_SLOT"):
            IntegrationEvidence(
                head_sha=FIX_AFTER_1526, maker_id=MAKER, checks=one, review=one
            )

    def test_the_same_actor_reporting_both_is_refused_as_a_self_review(self):
        # Distinct observations, correctly filed, one actor. The independence
        # rule catches this, not the slot rule.
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id="ci",
            checks=passing(
                EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
            ),
            review=passing(
                EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526, observer="ci"
            ),
        )

        assert decide_next_step(evidence).refusals == (Refusal.REVIEW_NOT_INDEPENDENT,)


class TestIdentityIsOneSpellingPerActor:
    """`observer_id` was stripped to test emptiness and compared unstripped, so
    a maker reviewed their own work by adding a space."""

    @pytest.mark.parametrize(
        "spelling", [f"{MAKER} ", f" {MAKER}", MAKER.upper(), f"{MAKER}\t"]
    )
    def test_a_maker_cannot_review_their_own_head_by_respelling_their_name(
        self, spelling
    ):
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=passing(
                EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
            ),
            review=passing(
                EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526, observer=spelling
            ),
        )

        decision = decide_next_step(evidence)

        assert decision.may_integrate is False
        assert decision.refusals == (Refusal.REVIEW_NOT_INDEPENDENT,)

    def test_and_a_genuinely_different_checker_still_passes(self):
        assert may_integrate(ready(FIX_AFTER_1526)) is True


class TestAHeadIsAFullCommitId:
    def test_a_trailing_newline_does_not_make_a_commit_id(self):
        # `$` matches before a trailing newline, so `re.match` accepted this --
        # which is what a head read from an unstripped capture looks like.
        with pytest.raises(ValueError):
            Observation(
                source=EvidenceSource.REQUIRED_CHECKS,
                head_sha=FIX_AFTER_1526 + "\n",
                passed=True,
            )

    def test_nor_does_leading_whitespace(self):
        with pytest.raises(ValueError):
            Observation(
                source=EvidenceSource.REQUIRED_CHECKS,
                head_sha=" " + FIX_AFTER_1526,
                passed=True,
            )


class TestTheHelperAndTheGateAgree:
    """`exact_head_verified()` omitted the independence check while the gate
    beside it enforced it, and its docstring invited a reader to substitute one
    for the other."""

    def test_the_helper_refuses_a_self_review_as_the_gate_does(self):
        evidence = IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=passing(
                EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
            ),
            review=passing(
                EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526, observer=MAKER
            ),
        )

        assert exact_head_verified(evidence) is False
        assert may_integrate(evidence) is False

    def test_and_agrees_on_the_honest_case(self):
        evidence = ready(FIX_AFTER_1526)
        assert exact_head_verified(evidence) is True
        assert may_integrate(evidence) is True


class TestTheHelperSaysWhatItDoes:
    """The docstring is part of the contract.

    `exact_head_verified()` reads the whole decision, not just the checks and
    review slots, so a recorded landing failure for THIS head turns it False
    even though checks and review both passed on it. A docstring that said only
    "checks and review both passed" would send a reader to this helper in the
    one case it refuses.
    """

    def _landed(self, head: str, *, passed: bool) -> IntegrationEvidence:
        return IntegrationEvidence(
            head_sha=FIX_AFTER_1526,
            maker_id=MAKER,
            checks=passing(
                EvidenceSource.REQUIRED_CHECKS, FIX_AFTER_1526, observer="ci"
            ),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, FIX_AFTER_1526),
            landed=Observation(
                source=EvidenceSource.LANDED_RESULT,
                head_sha=head,
                passed=passed,
                observer_id="verifier",
            ),
        )

    def test_a_landing_failure_for_this_head_withdraws_the_verification(self):
        evidence = self._landed(FIX_AFTER_1526, passed=False)

        assert decide_next_step(evidence).step is IntegrationStep.REPAIR
        assert exact_head_verified(evidence) is False

    def test_a_confirmed_landing_for_this_head_keeps_it(self):
        evidence = self._landed(FIX_AFTER_1526, passed=True)

        assert decide_next_step(evidence).step is IntegrationStep.RETIRE_LEASE
        assert exact_head_verified(evidence) is True

    def test_a_landing_failure_about_another_head_is_not_about_this_one(self):
        """It is stale, so it says nothing either way -- and the loop is sent
        back to verify the landing rather than to repair a failure it has no
        evidence of."""
        evidence = self._landed(MERGED_1524, passed=False)

        decision = decide_next_step(evidence)
        assert decision.step is IntegrationStep.VERIFY_LANDED_RESULT
        assert decision.refusals == (Refusal.LANDED_RESULT_STALE,)
        assert exact_head_verified(evidence) is True


class TestTheOneSurvivingMutant:
    """Counted from a controlled sweep, not from reading the code.

    34 mutants across `head_bound_integration`, `factory_policy` and
    `checker_dispatch`; 33 killed, 0 skipped, one survivor, named here because
    an unnamed survivor is a coverage claim nobody can check. A green baseline
    and an unmutated control copy went through the identical pipeline first --
    this harness has produced false results five times in this lineage, and a
    red control makes every "kill" an artifact of the copy.

    The survivor is `_FULL_SHA.fullmatch(...)` -> `.match(...)`. It is an
    EQUIVALENT mutant: the pattern ends in `\\Z`, which anchors at the absolute
    end of the string, so `match` already has to consume all of it. No test can
    distinguish the two, and writing one that appeared to would mean the
    anchor had been silently weakened.

    That is only true of `\\Z`. The `^[0-9a-f]{40}$` this replaced is a
    different rule, and `$` is exactly where the trailing-newline head got in.
    """

    PATTERN = r"[0-9a-f]{40}\Z"
    OLD_PATTERN = r"^[0-9a-f]{40}$"

    @pytest.mark.parametrize(
        "candidate",
        [
            "",
            "a" * 40,
            "a" * 40 + "\n",
            "\n" + "a" * 40,
            "a" * 40 + "x",
            "a" * 39,
            " " + "a" * 40,
            "a" * 40 + " ",
            "a" * 80,
            "A" * 40,
            "a" * 12,
        ],
    )
    def test_match_and_fullmatch_agree_under_the_absolute_end_anchor(self, candidate):
        pattern = re.compile(self.PATTERN)
        assert bool(pattern.match(candidate)) is bool(pattern.fullmatch(candidate))

    def test_and_the_anchor_this_replaced_did_not_agree(self):
        """`$` matches before a trailing newline. That is the whole difference,
        and an unstripped `git rev-parse` capture is exactly that string."""
        unstripped = "a" * 40 + "\n"
        assert re.compile(self.OLD_PATTERN).match(unstripped) is not None
        assert re.compile(self.PATTERN).fullmatch(unstripped) is None

    def test_and_the_module_refuses_it(self):
        with pytest.raises(ValueError):
            Observation(
                source=EvidenceSource.REQUIRED_CHECKS,
                head_sha="a" * 40 + "\n",
                passed=True,
            )
