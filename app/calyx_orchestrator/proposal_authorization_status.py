from __future__ import annotations

from dataclasses import dataclass

from .proposal_authorization import (
    ALLOWED_REVIEW_CLASSES,
    ProposalAuthorizationRegistry,
    ProposalDecision,
)


@dataclass(frozen=True, slots=True)
class ProposalReviewStatus:
    manifest_digest: str
    review_evidence_complete: bool
    code: str
    approved_classes: tuple[str, ...]
    pending_classes: tuple[str, ...]
    rejected_classes: tuple[str, ...]
    reviewer_conflict: bool = False
    git_mutation_authorized: bool = False
    commit_authorized: bool = False
    push_authorized: bool = False
    pull_request_creation_authorized: bool = False
    automatic_merge_authorized: bool = False


def proposal_review_status(
    registry: ProposalAuthorizationRegistry,
    *,
    manifest_digest: str,
) -> ProposalReviewStatus:
    """Summarize required repository review evidence without execution authority."""
    required = tuple(sorted(ALLOWED_REVIEW_CLASSES))
    approved: list[str] = []
    rejected: list[str] = []
    pending: list[str] = []
    approved_reviewers: list[str] = []

    for review_class in required:
        record = registry.records.get((manifest_digest, review_class))
        if record is None:
            pending.append(review_class)
        elif record.decision == ProposalDecision.APPROVED:
            approved.append(review_class)
            approved_reviewers.append(record.reviewer_id)
        else:
            rejected.append(review_class)

    reviewer_conflict = len(approved) == len(required) and len(
        set(approved_reviewers)
    ) != len(approved_reviewers)
    complete = (
        len(approved) == len(required)
        and not rejected
        and not pending
        and not reviewer_conflict
    )
    if rejected:
        code = "PROPOSAL_REVIEW_REJECTED"
    elif pending:
        code = "PROPOSAL_REVIEWS_PENDING"
    elif reviewer_conflict:
        code = "PROPOSAL_REVIEW_REVIEWER_CONFLICT"
    else:
        code = "PROPOSAL_REVIEW_EVIDENCE_COMPLETE"

    return ProposalReviewStatus(
        manifest_digest=manifest_digest,
        review_evidence_complete=complete,
        code=code,
        approved_classes=tuple(approved),
        pending_classes=tuple(pending),
        rejected_classes=tuple(rejected),
        reviewer_conflict=reviewer_conflict,
    )
