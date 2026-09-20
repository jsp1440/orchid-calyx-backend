"""Bind every piece of integration evidence to the commit it was produced against.

Three pull requests in this repository's merge-verifier lineage were merged
before the review of the head being merged had returned:

    #1524  merged `657b2f1`   opened 19:12, merged 22:07
    #1526  merged `85bb2b2`   opened 23:50, merged 00:06 -- the review of that
                              head returned at `6a57183`, 00:46, forty minutes
                              after the merge
    #1530  merged `9acced7`   opened 02:40, merged 02:47; no review ran

Each merge was authorized by evidence that was true of *some* commit, or by no
evidence at all. None was authorized by evidence true of the commit that
actually merged.

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
_FULL_SHA = re.compile(r"[0-9a-f]{40}\Z")


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

    Every member here is a step `decide_next_step` can actually return, and
    `TestTheVocabularyIsWhatTheCodeCanProduce` asserts that both ways round. A
    `REFILL` and a `BLOCKED` stood here and neither was reachable: refilling is
    what the CALLER does once the lease is retired, and nothing produced
    `BLOCKED` at all. The rest of this change removed a dead guard on the
    grounds that a guard which cannot fire is a claim of protection rather than
    protection; an outcome that cannot occur is the same claim in the same file.
    """

    RUN_CHECKS = "run_checks"
    REQUEST_INDEPENDENT_REVIEW = "request_independent_review"
    INTEGRATE = "integrate"
    VERIFY_LANDED_RESULT = "verify_landed_result"
    RETIRE_LEASE = "retire_lease"
    REPAIR = "repair"


class Refusal(StrEnum):
    """Why integration was refused. Every value names a specific missing fact."""

    # No `HEAD_NOT_A_FULL_SHA`: an observation that cannot name its commit is
    # refused by `__post_init__` before any decision is taken, so the refusal
    # could never be reached. No `REVIEW_INCONCLUSIVE` either -- `passed` is a
    # bool and there is no third state to report.
    CHECKS_NOT_RUN = "checks_not_run"
    CHECKS_STALE = "checks_stale"
    CHECKS_FAILED = "checks_failed"
    REVIEW_MISSING = "review_missing"
    REVIEW_STALE = "review_stale"
    REVIEW_NOT_INDEPENDENT = "review_not_independent"
    REVIEW_REJECTED = "review_rejected"
    LANDED_RESULT_UNVERIFIED = "landed_result_unverified"
    LANDED_RESULT_STALE = "landed_result_stale"


def same_actor(left: str, right: str) -> bool:
    """Whether two identity strings name the same actor.

    Public, and the only one. Before this there were two implementations that
    AGREED -- `_identity` here and `factory_policy._same_actor`, different in
    name, signature and body but semantically the same -- and three sites in
    `checker_dispatch` doing a bare `==`, which is a DIFFERENT rule and the
    reason this exists: it let a maker be selected as their own checker by
    adding a space, while the gate downstream refused the record that selection
    produced. Two rules that disagree about who someone is will eventually
    disagree about whether anyone checked.

    (An earlier version of this docstring called the `factory_policy` copy
    "byte-identical". It was not -- different name, signature, arity, docstring
    and body -- and calling a bare `==` a "copy of this rule" contradicted the
    point being made about it. An independent check diffed them. In a change
    about records asserting things that are not so, the docstring asserted
    something that was not so.)
    """
    return _identity(left) == _identity(right)


def _identity(value: str) -> str:
    """One spelling for one actor.

    The emptiness test stripped and the equality test did not, so `"M "`
    counted as a different actor from `"M"` and a maker could review their own
    work by adding a space. Case folds too: an actor id is a label, not a
    password.
    """
    return " ".join(value.split()).casefold()


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
        if not _FULL_SHA.fullmatch(self.head_sha):
            raise ValueError(f"HEAD_SHA_MUST_BE_40_HEX: {self.head_sha!r}")

    def is_about(self, head_sha: str) -> bool:
        """Whether this observation is about exactly that commit.

        Whole id, not a prefix: `git rev-parse` resolves a 7-hex prefix and two
        commits can share one, so a prefix comparison lets evidence about
        `abc1234fff…` authorize the integration of `abc1234000…`.
        """
        return self.head_sha == head_sha

    def by(self, actor_id: str) -> bool:
        """Whether the same actor produced this, however they spelled it."""
        return _identity(self.observer_id) == _identity(actor_id)


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
        if not _FULL_SHA.fullmatch(self.head_sha):
            raise ValueError(f"HEAD_SHA_MUST_BE_40_HEX: {self.head_sha!r}")
        if not self.maker_id.strip():
            raise ValueError("MAKER_ID_REQUIRED")
        # Nothing checked that an observation was filed in the slot it belongs
        # to, so a check run placed in `review` satisfied "an independent
        # review happened" -- an observation naming the right commit while
        # reporting on nothing. And the SAME observation could fill both slots,
        # so one check run counted as checks AND review.
        for slot, allowed in (
            ("checks", EvidenceSource.REQUIRED_CHECKS),
            ("review", EvidenceSource.INDEPENDENT_CHECKER),
            ("landed", EvidenceSource.LANDED_RESULT),
        ):
            observation = getattr(self, slot)
            if observation is not None and observation.source is not allowed:
                raise ValueError(
                    f"OBSERVATION_IN_WRONG_SLOT: {slot} holds {observation.source.value}"
                )
        # No separate "the same observation cannot fill both slots" guard: the
        # slot rule above already makes it impossible, because the two slots
        # require different sources. A guard that cannot fire is not protection,
        # it is a claim of protection.

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
    if not evidence.review.observer_id.strip() or evidence.review.by(evidence.maker_id):
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
    """Whether this exact head is verified: checks and an independent review
    both name it, both passed, and no landed result recorded for it says the
    integration did not produce what was verified.

    That last clause is not decoration. Saying only "checks and review passed"
    would describe a function that returns False after a landing failure, and a
    reader who trusted the sentence would reach for this helper in exactly the
    case it refuses.

    This is what `ValidationEvidence.exact_head_verified` was asking a caller to
    assert. It is derived here instead, from observations that had to name their
    commit in order to exist at all.
    """
    # Independence is part of it. A helper that omitted it accepted a maker
    # certifying their own head, while the gate beside it refused -- and its own
    # docstring invited a reader to substitute one for the other.
    return decide_next_step(evidence).step in {
        IntegrationStep.INTEGRATE,
        IntegrationStep.VERIFY_LANDED_RESULT,
        IntegrationStep.RETIRE_LEASE,
    }
