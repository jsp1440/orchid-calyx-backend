from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ReviewTaskState(StrEnum):
    OPEN = "OPEN"
    RESERVED = "RESERVED"
    IN_REVIEW = "IN_REVIEW"
    DECIDED = "DECIDED"
    ESCALATED = "ESCALATED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ReviewDecisionType(StrEnum):
    ACCEPT = "ACCEPT"
    MODIFY = "MODIFY"
    REJECT = "REJECT"
    DEFER = "DEFER"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class ReviewTaskInput:
    orchestration_id: str
    review_type: str
    risk_class: str
    routing_outcome: str
    required_capability: str
    candidate_ids: tuple[int, ...] = ()
    aggregate_version_ids: tuple[str, ...] = ()
    priority: int = 50
    scientific_impact_score: float = 0.5
    consensus_required: int = 1
    batch_key: str | None = None
    display_policy: str = "INTERNAL_RESEARCH_ONLY"
    embargoed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewDecisionInput:
    decision: ReviewDecisionType
    reviewer_id: str
    reviewer_capabilities: tuple[str, ...]
    comment: str | None = None
    modified_value: Any = None
    provenance: dict[str, Any] = field(default_factory=dict)
