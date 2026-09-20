"""The three merges that motivated this, and the rule that refuses them.

Every SHA below is real. #1524 was merged at `657b2f1` while its review was at
`6a57183`; #1526 at `85bb2b2` while its review was at `9acced7`; #1530 six
minutes after it was opened, before any review ran at all. In each case the
evidence on file was TRUE -- of a commit that was not the one being merged.
"""

from __future__ import annotations

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

#: Real commits from the lineage this module exists because of.
MERGED_1524 = "657b2f183c35852af10ca290730b03a23dd1d64e"
REVIEWED_1524 = "6a57183395c29f0a47b4a11cd86fabe34ac10d95"
MERGED_1526 = "85bb2b2d886a27f207cd3b1ee8d9837f8dfe5f11"
REVIEWED_1526 = "9acced7e703544c701b3730152b56ca558f9d394"

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
        """#1524: merged at 657b2f1, reviewed at 6a57183."""
        evidence = IntegrationEvidence(
            head_sha=MERGED_1524,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, MERGED_1524, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, REVIEWED_1524),
        )

        decision = decide_next_step(evidence)

        assert decision.may_integrate is False
        assert Refusal.REVIEW_STALE in decision.refusals
        assert decision.blocked_on_stale_evidence is True
        # The refusal names the commit the review was actually about, so an
        # operator can see at a glance that the evidence is real but misfiled.
        assert REVIEWED_1524[:12] in decision.reason
        assert decision.step is IntegrationStep.REQUEST_INDEPENDENT_REVIEW

    def test_the_same_holds_however_recent_the_review_is(self):
        """#1526: the review was NEWER than the merged head, and still not about it."""
        evidence = IntegrationEvidence(
            head_sha=MERGED_1526,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, MERGED_1526, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, REVIEWED_1526),
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
        # `REVIEWED_1524`, and it authorizes exactly that commit.
        assert may_integrate(ready(REVIEWED_1524)) is True


class TestAHeadThatMovedStartsAgain:
    def test_checks_from_the_previous_head_do_not_carry_forward(self):
        evidence = IntegrationEvidence(
            head_sha=REVIEWED_1526,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, MERGED_1526, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, REVIEWED_1526),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.RUN_CHECKS
        assert decision.refusals == (Refusal.CHECKS_STALE,)

    def test_the_earliest_missing_fact_is_the_one_reported(self):
        # Both are stale. Telling the operator to re-review first would send
        # them to redo work that the re-run of checks may change anyway.
        evidence = IntegrationEvidence(
            head_sha=REVIEWED_1526,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, MERGED_1526, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, MERGED_1526),
        )

        assert decide_next_step(evidence).step is IntegrationStep.RUN_CHECKS
        assert len(evidence.stale()) == 2

    def test_a_passing_review_of_a_failing_head_is_still_about_that_head(self):
        evidence = IntegrationEvidence(
            head_sha=REVIEWED_1524,
            maker_id=MAKER,
            checks=Observation(
                source=EvidenceSource.REQUIRED_CHECKS,
                head_sha=REVIEWED_1524,
                passed=False,
                observer_id="ci",
            ),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, REVIEWED_1524),
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
            Observation(source=EvidenceSource.REQUIRED_CHECKS, head_sha=head, passed=True)

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
            head_sha=REVIEWED_1524,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, REVIEWED_1524, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, REVIEWED_1524, observer=MAKER),
        )

        decision = decide_next_step(evidence)

        assert decision.may_integrate is False
        assert decision.refusals == (Refusal.REVIEW_NOT_INDEPENDENT,)

    def test_an_anonymous_review_is_not_an_independent_one(self):
        evidence = IntegrationEvidence(
            head_sha=REVIEWED_1524,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, REVIEWED_1524, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, REVIEWED_1524, observer="  "),
        )

        assert decide_next_step(evidence).refusals == (Refusal.REVIEW_NOT_INDEPENDENT,)


class TestTheLoopDoesNotEndAtTheMerge:
    def test_integration_is_followed_by_verifying_what_landed(self):
        decision = decide_next_step(ready(REVIEWED_1524))
        assert decision.step is IntegrationStep.INTEGRATE
        assert decision.may_integrate is True

    def test_a_confirmed_landing_retires_the_lease(self):
        evidence = IntegrationEvidence(
            head_sha=REVIEWED_1524,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, REVIEWED_1524, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, REVIEWED_1524),
            landed=passing(EvidenceSource.LANDED_RESULT, REVIEWED_1524, observer="verifier"),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.RETIRE_LEASE
        assert decision.may_integrate is False
        assert decision.refusals == ()

    def test_a_merge_that_did_not_land_the_verified_result_goes_to_repair(self):
        # The #706 failure: the merge API said yes and the tree was wrong.
        evidence = IntegrationEvidence(
            head_sha=REVIEWED_1524,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, REVIEWED_1524, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, REVIEWED_1524),
            landed=Observation(
                source=EvidenceSource.LANDED_RESULT,
                head_sha=REVIEWED_1524,
                passed=False,
                observer_id="verifier",
            ),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.REPAIR
        assert decision.refusals == (Refusal.LANDED_RESULT_UNVERIFIED,)

    def test_a_landing_check_about_another_head_does_not_close_the_loop(self):
        evidence = IntegrationEvidence(
            head_sha=REVIEWED_1524,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, REVIEWED_1524, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, REVIEWED_1524),
            landed=passing(EvidenceSource.LANDED_RESULT, MERGED_1524, observer="verifier"),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.VERIFY_LANDED_RESULT
        assert decision.refusals == (Refusal.LANDED_RESULT_STALE,)


class TestExactHeadVerifiedIsDerivedNotAsserted:
    def test_it_is_true_only_when_both_facts_name_this_head_and_pass(self):
        assert exact_head_verified(ready(REVIEWED_1524)) is True

    @pytest.mark.parametrize(
        "checks_head,review_head,checks_pass,review_pass",
        [
            (MERGED_1524, REVIEWED_1524, True, True),
            (REVIEWED_1524, MERGED_1524, True, True),
            (REVIEWED_1524, REVIEWED_1524, False, True),
            (REVIEWED_1524, REVIEWED_1524, True, False),
        ],
    )
    def test_and_false_for_every_way_of_being_about_something_else(
        self, checks_head, review_head, checks_pass, review_pass
    ):
        evidence = IntegrationEvidence(
            head_sha=REVIEWED_1524,
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
        assert exact_head_verified(IntegrationEvidence(head_sha=REVIEWED_1524, maker_id=MAKER)) is False


class TestTheDecisionIsReproducible:
    def test_the_same_record_always_gives_the_same_decision(self):
        evidence = ready(REVIEWED_1524)
        first = decide_next_step(evidence)
        second = decide_next_step(evidence)

        assert first == second
        assert isinstance(first, IntegrationDecision)

    def test_stale_lists_every_observation_about_another_commit(self):
        evidence = IntegrationEvidence(
            head_sha=REVIEWED_1524,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, MERGED_1524, observer="ci"),
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, MERGED_1526),
            landed=passing(EvidenceSource.LANDED_RESULT, REVIEWED_1524, observer="v"),
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
            head_sha=REVIEWED_1524,
            maker_id=MAKER,
            review=passing(EvidenceSource.INDEPENDENT_CHECKER, REVIEWED_1524),
        )

        decision = decide_next_step(evidence)

        assert decision.step is IntegrationStep.RUN_CHECKS
        assert decision.refusals == (Refusal.CHECKS_NOT_RUN,)
        assert decision.may_integrate is False

    def test_a_review_that_rejected_this_head_routes_to_repair(self):
        evidence = IntegrationEvidence(
            head_sha=REVIEWED_1524,
            maker_id=MAKER,
            checks=passing(EvidenceSource.REQUIRED_CHECKS, REVIEWED_1524, observer="ci"),
            review=Observation(
                source=EvidenceSource.INDEPENDENT_CHECKER,
                head_sha=REVIEWED_1524,
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
