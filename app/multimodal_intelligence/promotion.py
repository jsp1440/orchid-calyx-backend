from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .operator import MultimodalError, OperationRecord


@dataclass(frozen=True, slots=True)
class PromotionPlan:
    operation_id: str
    target: str
    eligible: bool
    blockers: tuple[str, ...]
    payload: dict[str, Any]
    automatic_execution: bool = False


def build_candidate_knowledge_promotion_plan(record: OperationRecord) -> PromotionPlan:
    """Create a non-executing promotion plan for a reviewed literature operation.

    This deliberately does not call CandidateExtractionService. It provides a
    deterministic boundary between review approval and a later governed handoff.
    """
    blockers: list[str] = []
    if record.operation_type != "literature_validation":
        blockers.append("LITERATURE_OPERATION_REQUIRED")
    if record.state != "review_approved" or record.review is None:
        blockers.append("HUMAN_REVIEW_APPROVAL_REQUIRED")
    if record.result.get("publication_allowed") is not False:
        blockers.append("PUBLICATION_BOUNDARY_INVALID")
    if not record.result.get("claim_id"):
        blockers.append("CLAIM_ID_REQUIRED")

    return PromotionPlan(
        operation_id=record.operation_id,
        target="candidate_knowledge",
        eligible=not blockers,
        blockers=tuple(blockers),
        payload={
            "operation_id": record.operation_id,
            "claim_id": record.result.get("claim_id"),
            "canonical_taxon_id": record.result.get("canonical_taxon_id"),
            "confidence": record.result.get("confidence"),
            "contradictions": record.result.get("contradictions", []),
            "review": asdict(record.review) if record.review else None,
            "request_hash": record.request_hash,
            "provenance": record.provenance,
            "published": False,
            "review_required": True,
        },
        automatic_execution=False,
    )


def require_eligible_promotion(plan: PromotionPlan) -> PromotionPlan:
    if not plan.eligible:
        raise MultimodalError(
            "PROMOTION_NOT_ELIGIBLE",
            f"Promotion is blocked: {', '.join(plan.blockers)}",
        )
    return plan
