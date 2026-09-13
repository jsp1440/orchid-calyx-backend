"""Governance states and promotion proposals for CALYX-EVOLVE-001.

The strongest statement this module makes is what it does *not* contain.  There
is no approve, activate, or publish transition anywhere in the evolve package:
the only outcome a successful experiment can produce is a proposal in state
``review_pending``, and moving beyond that is a human scientific review action
owned by the existing taxonomy activation and publication surfaces, not by this
loop.

``GOVERNANCE_STATES`` and ``PROMOTION_STATES`` are exhaustive.  A test asserts
that no activation-shaped state or callable exists in the package.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from runtime.calyx_evolve.provenance import content_hash
from runtime.calyx_evolve.redaction import assert_inspectable

GOVERNANCE_DRAFT = "DRAFT"
GOVERNANCE_ARCHIVED = "ARCHIVED"

#: Every governance state a campaign may occupy in this phase.
GOVERNANCE_STATES: tuple[str, ...] = (GOVERNANCE_DRAFT, GOVERNANCE_ARCHIVED)

SCOPE_STAGING_ONLY = "STAGING_ONLY"

#: Every execution scope this phase permits.
EXECUTION_SCOPES: tuple[str, ...] = (SCOPE_STAGING_ONLY,)

PROMOTION_REVIEW_PENDING = "review_pending"
PROMOTION_BLOCKED = "blocked"

#: Every promotion state this loop can produce.  Approval and activation are
#: deliberately absent.
PROMOTION_STATES: tuple[str, ...] = (PROMOTION_REVIEW_PENDING, PROMOTION_BLOCKED)


class GovernanceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PromotionProposal:
    """A request for human scientific review.  Never an activation."""

    campaign_id: str
    run_id: str
    candidate_id: str
    state: str
    rationale: str
    blockers: tuple[str, ...] = ()
    metric_summary: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""

    #: Invariants asserted on every proposal.
    requires_human_scientific_review: bool = True
    taxonomy_activation_permitted: bool = False
    knowledge_graph_publication_permitted: bool = False
    external_publication_permitted: bool = False

    def __post_init__(self) -> None:
        if self.state not in PROMOTION_STATES:
            raise GovernanceError(
                f"promotion state {self.state!r} is not one of {list(PROMOTION_STATES)}"
            )
        if not self.requires_human_scientific_review:
            raise GovernanceError("human scientific review is mandatory and cannot be waived")
        if (
            self.taxonomy_activation_permitted
            or self.knowledge_graph_publication_permitted
            or self.external_publication_permitted
        ):
            raise GovernanceError("this phase grants no activation or publication authority")
        if self.state == PROMOTION_BLOCKED and not self.blockers:
            raise GovernanceError("a blocked proposal must name its blockers")
        if self.state == PROMOTION_REVIEW_PENDING and self.blockers:
            raise GovernanceError("a review-pending proposal must have no blockers")
        assert_inspectable(
            {"rationale": self.rationale, "metric_summary": dict(self.metric_summary)}
        )

    @property
    def proposal_id(self) -> str:
        return content_hash(
            {
                "campaign_id": self.campaign_id,
                "run_id": self.run_id,
                "candidate_id": self.candidate_id,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "campaign_id": self.campaign_id,
            "run_id": self.run_id,
            "candidate_id": self.candidate_id,
            "state": self.state,
            "rationale": self.rationale,
            "blockers": list(self.blockers),
            "metric_summary": dict(self.metric_summary),
            "created_at": self.created_at,
            "requires_human_scientific_review": True,
            "taxonomy_activation_permitted": False,
            "knowledge_graph_publication_permitted": False,
            "external_publication_permitted": False,
        }


def build_promotion_proposal(
    *,
    campaign_id: str,
    run_id: str,
    candidate_id: str,
    blockers: Iterable[str],
    rationale: str,
    metric_summary: Mapping[str, Any],
    created_at: str,
) -> PromotionProposal:
    """Return a review-pending proposal, or a blocked one naming every blocker."""

    ordered = tuple(sorted({str(blocker) for blocker in blockers if str(blocker).strip()}))
    if ordered:
        return PromotionProposal(
            campaign_id=campaign_id,
            run_id=run_id,
            candidate_id=candidate_id,
            state=PROMOTION_BLOCKED,
            rationale=rationale,
            blockers=ordered,
            metric_summary=dict(metric_summary),
            created_at=created_at,
        )
    return PromotionProposal(
        campaign_id=campaign_id,
        run_id=run_id,
        candidate_id=candidate_id,
        state=PROMOTION_REVIEW_PENDING,
        rationale=rationale,
        blockers=(),
        metric_summary=dict(metric_summary),
        created_at=created_at,
    )


def assert_governance(state: str, scope: str) -> None:
    """Fail closed on any governance state or scope this phase does not permit."""

    if state not in GOVERNANCE_STATES:
        raise GovernanceError(f"governance state {state!r} is not permitted in this phase")
    if scope not in EXECUTION_SCOPES:
        raise GovernanceError(f"execution scope {scope!r} is not permitted in this phase")
