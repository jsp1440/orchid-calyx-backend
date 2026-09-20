"""Bind every piece of integration evidence to the commit it was produced against.

Three pull requests in this repository's merge-verifier lineage were merged
before their reviews finished -- #1524 at `657b2f1`, #1526 at `85bb2b2`, #1530
six minutes after it was opened. Each merge was authorized by evidence that was
true of *some* commit. None of them was authorized by evidence true of the
commit that actually merged.

The existing gate could not tell the difference. `ValidationEvidence` carried
`exact_head_verified: bool` -- a fact the CALLER asserts -- and
`checker_dispatch` derived it by comparing the checker's head against the head
recorded in the ASSIGNMENT. Both comparisons are satisfied by a stale head: if
the pull request moves after the assignment is written, the checker still
verified the assignment's head, the boolean is still true, and the gate still
says `AUTO_INTEGRATE` for a commit nobody checked.

So evidence here is never a bare boolean. Every fact carries the 40-hex commit
it is about, and the decision is a comparison the gate performs rather than a
claim it accepts. The rule is one line: **every observation must name the same
commit as the pull request head observed at decision time.** A head that moved
does not invalidate the old evidence -- the old evidence remains perfectly true
of the old commit, which is exactly why it is dangerous. It simply stops being
evidence about what is being merged.

Nothing here calls the network, reads a credential, or shells out. It takes
recorded observations and returns a decision, so the decision is reproducible
from the record and testable without GitHub.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

#: A full commit id. Abbreviations are refused on purpose: `git rev-parse`
#: happily resolves a 7-hex prefix, two commits can share one, and "the head
#: I checked" must not be a string that could name something else later.
_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


class EvidenceSource(StrEnum):
    """Who produced an observation. Named so a refusal can say which one is stale."""

    PULL_REQUEST = "pull_request"
    REQUIRED_CHECKS = "required_checks"
    INDEPENDENT_CHECKER = "independent_checker"
    LANDED_RESULT = "landed_result"


class IntegrationStep(StrEnum):
    """The loop, in the only order that makes each step mean anything.

    Each step is authorized by evidence about the head the previous step ran
    against. Skipping one, or carrying evidence forward from a different head,
    is what this module exists to refuse.
    """

    RUN_CHECKS = "run_checks"
    REQUEST_INDEPENDENT_REVIEW = "request_independent_review"
    INTEGRATE = "integrate"
    VERIFY_LANDED_RESULT = "verify_landed_result"
    RETIRE_LEASE = "retire_lease"
    REFILL = "refill"
    REPAIR = "repair"
    BLOCKED = "blocked"


class Refusal(StrEnum):
    """Why integration was refused. Every value names a specific missing fact."""

    HEAD_NOT_A_FULL_SHA = "head_not_a_full_sha"
    CHECKS_NOT_RUN = "checks_not_run"
    CHECKS_STALE = "checks_stale"
    CHECKS_FAILED = "checks_failed"
    REVIEW_MISSING = "review_missing"
    REVIEW_STALE = "review_stale"
    REVIEW_NOT_INDEPENDENT = "review_not_independent"
    REVIEW_REJECTED = "review_rejected"
    REVIEW_INCONCLUSIVE = "review_inconclusive"
    LANDED_RESULT_UNVERIFIED = "landed_result_unverified"
    LANDED_RESULT_STALE = "landed_result_stale"


@dataclass(frozen=True, slots=True)
class Observation:
    """One fact, and the commit it is a fact about.

    `head_sha` is not optional and not abbreviated. An observation that cannot
    name its commit is not an observation; it is a recollection.
    """

    source: EvidenceSource
    head_sha: str
    passed: bool
    observer_id: str = ""
    detail: str = ""

    def __post_init__(self) -> None:
        if not _FULL_SHA.match(self.head_sha):
            raise ValueError(f"HEAD_SHA_MUST_BE_40_HEX: {self.head_sha!r}")

    def is_about(self, head_sha: str) -> bool:
        """Whether this observation is about exactly that commit."""
        return self.head_sha == head_sha


@dataclass(frozen=True, slots=True)
class IntegrationEvidence:
    """Everything known about a pull request, each fact bound to its commit.

    `head_sha` is the pull request's head AS OBSERVED NOW, not when the work
    started. That is the whole point: it is the commit that would merge, and
    every other observation is measured against it.
    """

    head_sha: str
    maker_id: str
    checks: Observation | None = None
    review: Observation | None = None
    landed: Observation | None = None

    def __post_init__(self) -> None:
        if not _FULL_SHA.match(self.head_sha):
            raise ValueError(f"HEAD_SHA_MUST_BE_40_HEX: {self.head_sha!r}")
        if not self.maker_id.strip():
            raise ValueError("MAKER_ID_REQUIRED")

    def stale(self) -> tuple[Observation, ...]:
        """Observations that are about some other commit.

        They are not wrong. They are true of the commit they name, which is why
        reading them as evidence about this one is the failure this prevents.
        """
        return tuple(
            observation
            for observation in (self.checks, self.review, self.landed)
            if observation is not None and not observation.is_about(self.head_sha)
        )


@dataclass(frozen=True, slots=True)
class IntegrationDecision:
    """What may happen next, and the exact reason."""

    step: IntegrationStep
    reason: str
    head_sha: str
    refusals: tuple[Refusal, ...] = ()
    may_integrate: bool = False

    @property
    def blocked_on_stale_evidence(self) -> bool:
        """Whether anything was refused because it named a different commit."""
        return any(
            refusal
            in {
                Refusal.CHECKS_STALE,
                Refusal.REVIEW_STALE,
                Refusal.LANDED_RESULT_STALE,
            }
            for refusal in self.refusals
        )


def decide_next_step(evidence: IntegrationEvidence) -> IntegrationDecision:
    """The next step the loop may take, given what is known about THIS head.

    Ordered so that each refusal names the earliest missing fact rather than the
    most convenient one. An empty `refusals` with `may_integrate` false means the
    change has already integrated and the loop is finishing.
    """

    head = evidence.head_sha

    if evidence.checks is None:
        return IntegrationDecision(
            step=IntegrationStep.RUN_CHECKS,
            reason="NO_CHECK_RESULT_FOR_THIS_HEAD",
            head_sha=head,
            refusals=(Refusal.CHECKS_NOT_RUN,),
        )
    if not evidence.checks.is_about(head):
        return IntegrationDecision(
            step=IntegrationStep.RUN_CHECKS,
            reason=f"CHECKS_RAN_AGAINST_{evidence.checks.head_sha[:12]}_NOT_THIS_HEAD",
            head_sha=head,
            refusals=(Refusal.CHECKS_STALE,),
        )
    if not evidence.checks.passed:
        return IntegrationDecision(
            step=IntegrationStep.REPAIR,
            reason="REQUIRED_CHECKS_FAILED_ON_THIS_HEAD",
            head_sha=head,
            refusals=(Refusal.CHECKS_FAILED,),
        )

    if evidence.review is None:
        return IntegrationDecision(
            step=IntegrationStep.REQUEST_INDEPENDENT_REVIEW,
            reason="NO_INDEPENDENT_REVIEW_FOR_THIS_HEAD",
            head_sha=head,
            refusals=(Refusal.REVIEW_MISSING,),
        )
    if not evidence.review.is_about(head):
        return IntegrationDecision(
            step=IntegrationStep.REQUEST_INDEPENDENT_REVIEW,
            reason=f"REVIEW_VERIFIED_{evidence.review.head_sha[:12]}_NOT_THIS_HEAD",
            head_sha=head,
            refusals=(Refusal.REVIEW_STALE,),
        )
    # A maker reviewing their own work is one identity wearing two labels, and
    # the whole value of the review is that it is not the same judgement twice.
    if not evidence.review.observer_id.strip() or evidence.review.observer_id == evidence.maker_id:
        return IntegrationDecision(
            step=IntegrationStep.REQUEST_INDEPENDENT_REVIEW,
            reason="REVIEW_NOT_INDEPENDENT_OF_THE_MAKER",
            head_sha=head,
            refusals=(Refusal.REVIEW_NOT_INDEPENDENT,),
        )
    if not evidence.review.passed:
        return IntegrationDecision(
            step=IntegrationStep.REPAIR,
            reason="INDEPENDENT_REVIEW_REJECTED_THIS_HEAD",
            head_sha=head,
            refusals=(Refusal.REVIEW_REJECTED,),
        )

    if evidence.landed is None:
        return IntegrationDecision(
            step=IntegrationStep.INTEGRATE,
            reason="CHECKS_AND_REVIEW_BOTH_VERIFIED_THIS_HEAD",
            head_sha=head,
            may_integrate=True,
        )

    # Integration has happened. The loop is not finished until the result is
    # confirmed, because a merge API's success is not a statement about the
    # resulting tree -- which is what the rest of this lineage is about.
    if not evidence.landed.is_about(head):
        return IntegrationDecision(
            step=IntegrationStep.VERIFY_LANDED_RESULT,
            reason=f"LANDED_CHECK_WAS_ABOUT_{evidence.landed.head_sha[:12]}_NOT_THIS_HEAD",
            head_sha=head,
            refusals=(Refusal.LANDED_RESULT_STALE,),
        )
    if not evidence.landed.passed:
        return IntegrationDecision(
            step=IntegrationStep.REPAIR,
            reason="INTEGRATION_DID_NOT_LAND_THE_VERIFIED_RESULT",
            head_sha=head,
            refusals=(Refusal.LANDED_RESULT_UNVERIFIED,),
        )

    return IntegrationDecision(
        step=IntegrationStep.RETIRE_LEASE,
        reason="LANDED_RESULT_CONFIRMED_ON_THIS_HEAD",
        head_sha=head,
    )


def may_integrate(evidence: IntegrationEvidence) -> bool:
    """The single place to ask. There is no other way to get a yes."""
    return decide_next_step(evidence).may_integrate


def exact_head_verified(evidence: IntegrationEvidence) -> bool:
    """Whether checks AND review both name this exact head, and both passed.

    This is what `ValidationEvidence.exact_head_verified` was asking a caller to
    assert. It is derived here instead, from observations that had to name their
    commit in order to exist at all.
    """
    return (
        evidence.checks is not None
        and evidence.review is not None
        and evidence.checks.is_about(evidence.head_sha)
        and evidence.review.is_about(evidence.head_sha)
        and evidence.checks.passed
        and evidence.review.passed
    )
