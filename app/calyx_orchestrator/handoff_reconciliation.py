"""Decide whether a reported off-GitHub completion is durable evidence.

A session that cannot write to GitHub can still finish work, and it can still
report that it did: a local branch name, a changed-file count, a test count.
Issue #1757 is that case -- a desktop session reported `claude/r1-autonomy-next`,
22 changed files and 11,121 passing tests, and none of it was on GitHub.

Those reports are context. They are not evidence, because nothing ties them to a
commit anyone else can inspect. Completion is the durable chain

    issue -> branch -> non-empty commit -> draft PR -> exact head
          -> executed checks on that head -> recorded remaining gap

and this module reports the first link of that chain that is missing. The
reported claim is accepted only to say *what* was claimed; no field of it can
supply a link. A claimed test count does not stand in for a check run, and a
claimed branch does not stand in for a branch GitHub reports.

`completion_receipt_contract` validates the SHAPE of a receipt. This decides
whether there is anything on GitHub for a receipt to describe.

Nothing here calls the network, reads a credential, or shells out. It takes
recorded observations and returns a decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

#: A full commit id, for the same reason `head_bound_integration` refuses
#: prefixes: two commits can share one.
_FULL_SHA = re.compile(r"[0-9a-f]{40}\Z")


class ChainLink(StrEnum):
    """The durable chain, in order. A missing link is reported by its name."""

    ISSUE = "issue"
    BRANCH = "branch"
    NON_EMPTY_COMMIT = "non_empty_commit"
    DRAFT_PR = "draft_pr"
    EXACT_HEAD = "exact_head"
    EXECUTED_CHECKS = "executed_checks"
    RECORDED_GAP = "recorded_gap"


class CheckState(StrEnum):
    """What the required checks did on the head they name.

    `NOT_EXECUTED` is a job that never got a runner. It is
    `CI_INFRASTRUCTURE_BLOCKED`, not a code failure and not green.
    """

    NOT_RUN = "not_run"
    NOT_EXECUTED = "not_executed"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class HandoffState(StrEnum):
    """Where the reported work stands, judged only by durable observations."""

    #: Something was claimed and none of the chain exists on GitHub.
    LOCAL_CLAIM_ONLY = "local_claim_only"
    #: Some of the chain exists; `missing` names the first absent link.
    INCOMPLETE = "incomplete"
    #: The chain exists up to checks on the exact head, which have not finished.
    IN_VALIDATION = "in_validation"
    #: Checks on the exact head never executed. A blocker, not a result.
    CI_INFRASTRUCTURE_BLOCKED = "ci_infrastructure_blocked"
    #: Checks executed on the exact head and failed.
    REPAIR = "repair"
    #: Every link exists and the checks on the exact head passed.
    DELIVERED = "delivered"


@dataclass(frozen=True, slots=True)
class ReportedClaim:
    """What an off-GitHub session said it did. Recorded, never trusted."""

    reporter_id: str
    branch: str = ""
    changed_file_count: int | None = None
    tests_passed: int | None = None


@dataclass(frozen=True, slots=True)
class DurableObservation:
    """What GitHub reports now. The only input that can supply a link.

    `branch_head_sha` is the branch tip as GitHub reports it and `pr_head_sha`
    is the pull request's head; `checks_head_sha` names the commit the checks
    ran on. Each must be a full 40-hex id when present.
    """

    issue_number: int | None = None
    branch: str = ""
    branch_head_sha: str = ""
    commits_ahead_of_base: int = 0
    pr_number: int | None = None
    pr_is_draft: bool = False
    pr_head_sha: str = ""
    checks_head_sha: str = ""
    checks: CheckState = CheckState.NOT_RUN
    remaining_gap_recorded: bool = False

    def __post_init__(self) -> None:
        for name in ("branch", "branch_head_sha", "pr_head_sha", "checks_head_sha"):
            if type(getattr(self, name)) is not str:
                raise TypeError(f"{name.upper()}_MUST_BE_STR")
        for name in ("issue_number", "pr_number"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value <= 0):
                error = f"{name.upper()}_MUST_BE_POSITIVE_INT_OR_NONE"
                if type(value) is not int:
                    raise TypeError(error)
                raise ValueError(error)
        for name in ("pr_is_draft", "remaining_gap_recorded"):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"{name.upper()}_MUST_BE_BOOL")
        if not isinstance(self.checks, CheckState):
            raise TypeError("CHECKS_MUST_BE_CHECK_STATE")
        for name in ("branch_head_sha", "pr_head_sha", "checks_head_sha"):
            value = getattr(self, name)
            if value and not _FULL_SHA.fullmatch(value):
                raise ValueError(f"HEAD_SHA_MUST_BE_40_HEX: {name}={value!r}")
        if type(self.commits_ahead_of_base) is not int:
            raise TypeError("COMMITS_AHEAD_MUST_BE_NON_NEGATIVE_INT")
        if self.commits_ahead_of_base < 0:
            raise ValueError("COMMITS_AHEAD_MUST_BE_NON_NEGATIVE_INT")


@dataclass(frozen=True, slots=True)
class HandoffDecision:
    """The state, the first missing link, and why."""

    state: HandoffState
    reason: str
    missing: ChainLink | None = None
    head_sha: str = ""
    claimed_branch_observed: bool = False

    @property
    def is_durable_completion(self) -> bool:
        return self.state is HandoffState.DELIVERED


def _first_missing(observed: DurableObservation) -> tuple[ChainLink, str] | None:
    if observed.issue_number is None or observed.issue_number <= 0:
        return ChainLink.ISSUE, "NO_LINKED_ISSUE"
    if not observed.branch.strip() or not observed.branch_head_sha:
        return ChainLink.BRANCH, "NO_BRANCH_ON_GITHUB"
    if observed.commits_ahead_of_base == 0:
        return ChainLink.NON_EMPTY_COMMIT, "BRANCH_HAS_NO_COMMITS_AHEAD_OF_BASE"
    if observed.pr_number is None or observed.pr_number <= 0:
        return ChainLink.DRAFT_PR, "NO_PULL_REQUEST_FOR_BRANCH"
    if not observed.pr_is_draft:
        return ChainLink.DRAFT_PR, "PULL_REQUEST_IS_NOT_DRAFT"
    if observed.pr_head_sha != observed.branch_head_sha:
        return ChainLink.EXACT_HEAD, "PR_HEAD_DOES_NOT_MATCH_BRANCH_HEAD"
    if observed.checks is CheckState.NOT_RUN or not observed.checks_head_sha:
        return ChainLink.EXECUTED_CHECKS, "NO_CHECK_RESULT_FOR_THIS_HEAD"
    if observed.checks_head_sha != observed.pr_head_sha:
        return (
            ChainLink.EXECUTED_CHECKS,
            f"CHECKS_RAN_AGAINST_{observed.checks_head_sha[:12]}_NOT_THIS_HEAD",
        )
    return None


def reconcile_handoff(
    claim: ReportedClaim | None, observed: DurableObservation
) -> HandoffDecision:
    """Judge a reported completion by what GitHub holds, never by the report.

    The claim only decides whether a missing chain is reported as
    `LOCAL_CLAIM_ONLY` (someone said it was done) rather than `INCOMPLETE`.
    """

    head = observed.pr_head_sha or observed.branch_head_sha
    claimed_branch_observed = bool(
        claim is not None
        and claim.branch.strip()
        and claim.branch.strip() == observed.branch.strip()
        and observed.branch_head_sha
    )

    missing = _first_missing(observed)
    if missing is not None:
        link, reason = missing
        nothing_durable = link in {ChainLink.ISSUE, ChainLink.BRANCH}
        state = (
            HandoffState.LOCAL_CLAIM_ONLY
            if claim is not None and nothing_durable
            else HandoffState.INCOMPLETE
        )
        return HandoffDecision(
            state=state,
            reason=reason,
            missing=link,
            head_sha=head,
            claimed_branch_observed=claimed_branch_observed,
        )

    if observed.checks is CheckState.NOT_EXECUTED:
        return HandoffDecision(
            state=HandoffState.CI_INFRASTRUCTURE_BLOCKED,
            reason="CHECKS_HAD_NO_RUNNER_FOR_THIS_HEAD",
            missing=ChainLink.EXECUTED_CHECKS,
            head_sha=head,
            claimed_branch_observed=claimed_branch_observed,
        )
    if observed.checks is CheckState.PENDING:
        return HandoffDecision(
            state=HandoffState.IN_VALIDATION,
            reason="CHECKS_PENDING_ON_THIS_HEAD",
            missing=ChainLink.EXECUTED_CHECKS,
            head_sha=head,
            claimed_branch_observed=claimed_branch_observed,
        )
    if observed.checks is CheckState.FAILED:
        return HandoffDecision(
            state=HandoffState.REPAIR,
            reason="CHECKS_FAILED_ON_THIS_HEAD",
            head_sha=head,
            claimed_branch_observed=claimed_branch_observed,
        )
    if observed.checks is not CheckState.PASSED:
        raise ValueError("UNHANDLED_CHECK_STATE")
    if not observed.remaining_gap_recorded:
        return HandoffDecision(
            state=HandoffState.INCOMPLETE,
            reason="NO_REMAINING_GAP_OR_TERMINAL_EVIDENCE_RECORDED",
            missing=ChainLink.RECORDED_GAP,
            head_sha=head,
            claimed_branch_observed=claimed_branch_observed,
        )
    return HandoffDecision(
        state=HandoffState.DELIVERED,
        reason="DURABLE_CHAIN_COMPLETE_ON_THIS_HEAD",
        head_sha=head,
        claimed_branch_observed=claimed_branch_observed,
    )
