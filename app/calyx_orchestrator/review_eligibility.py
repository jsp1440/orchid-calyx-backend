from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ReviewClass(StrEnum):
    SCIENTIFIC = "scientific"
    LICENSING = "licensing"
    SECURITY = "security"
    OPERATIONAL = "operational"


class ReviewDecisionState(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"


@dataclass(frozen=True, slots=True)
class ReviewRequest:
    request_id: str
    artifact_id: str
    requested_by: str
    required_classes: tuple[ReviewClass, ...]
    producer_id: str

    def validate(self) -> None:
        if not self.request_id.strip():
            raise ValueError("REVIEW_REQUEST_ID_REQUIRED")
        if not self.artifact_id.strip():
            raise ValueError("REVIEW_ARTIFACT_REQUIRED")
        if not self.requested_by.strip() or not self.producer_id.strip():
            raise ValueError("REVIEW_ACTOR_REQUIRED")
        if not self.required_classes:
            raise ValueError("REVIEW_CLASS_REQUIRED")
        if len(set(self.required_classes)) != len(self.required_classes):
            raise ValueError("DUPLICATE_REVIEW_CLASS")


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    decision_id: str
    request_id: str
    review_class: ReviewClass
    reviewer_id: str
    reviewer_roles: tuple[str, ...]
    state: ReviewDecisionState
    rationale: str

    def validate_for(self, request: ReviewRequest) -> None:
        if not self.decision_id.strip():
            raise ValueError("REVIEW_DECISION_ID_REQUIRED")
        if self.request_id != request.request_id:
            raise ValueError("REVIEW_REQUEST_MISMATCH")
        if self.review_class not in request.required_classes:
            raise ValueError("UNREQUESTED_REVIEW_CLASS")
        if self.reviewer_id in {request.requested_by, request.producer_id}:
            raise PermissionError("SELF_APPROVAL_PROHIBITED")
        if self.review_class.value not in self.reviewer_roles:
            raise PermissionError("REVIEWER_ROLE_REQUIRED")
        if not self.rationale.strip():
            raise ValueError("REVIEW_RATIONALE_REQUIRED")


@dataclass(frozen=True, slots=True)
class ReleaseEligibility:
    artifact_id: str
    eligible: bool
    code: str
    approved_classes: tuple[str, ...]
    pending_classes: tuple[str, ...]
    rejected_classes: tuple[str, ...]
    changes_requested_classes: tuple[str, ...]


@dataclass(slots=True)
class ReviewRegistry:
    requests: dict[str, ReviewRequest] = field(default_factory=dict)
    decisions: dict[str, ReviewDecision] = field(default_factory=dict)

    def request(self, item: ReviewRequest) -> ReviewRequest:
        item.validate()
        existing = self.requests.get(item.request_id)
        if existing is not None and existing != item:
            raise ValueError("IMMUTABLE_REVIEW_REQUEST_CONFLICT")
        self.requests[item.request_id] = item
        return item

    def decide(self, decision: ReviewDecision) -> ReviewDecision:
        request = self.require_request(decision.request_id)
        decision.validate_for(request)
        existing = self.decisions.get(decision.decision_id)
        if existing is not None and existing != decision:
            raise ValueError("IMMUTABLE_REVIEW_DECISION_CONFLICT")
        for recorded in self.decisions.values():
            if recorded.request_id == decision.request_id and recorded.review_class == decision.review_class:
                if recorded != decision:
                    raise ValueError("AUTHORITATIVE_REVIEW_ALREADY_RECORDED")
                return recorded
        self.decisions[decision.decision_id] = decision
        return decision

    def eligibility(self, request_id: str) -> ReleaseEligibility:
        request = self.require_request(request_id)
        by_class = {
            decision.review_class: decision
            for decision in self.decisions.values()
            if decision.request_id == request_id
        }
        approved = tuple(sorted(item.value for item in request.required_classes if by_class.get(item) and by_class[item].state == ReviewDecisionState.APPROVED))
        rejected = tuple(sorted(item.value for item in request.required_classes if by_class.get(item) and by_class[item].state == ReviewDecisionState.REJECTED))
        changes = tuple(sorted(item.value for item in request.required_classes if by_class.get(item) and by_class[item].state == ReviewDecisionState.CHANGES_REQUESTED))
        pending = tuple(sorted(item.value for item in request.required_classes if item not in by_class))
        eligible = len(approved) == len(request.required_classes) and not rejected and not changes and not pending
        if rejected:
            code = "REVIEW_REJECTED"
        elif changes:
            code = "CHANGES_REQUESTED"
        elif pending:
            code = "REVIEWS_PENDING"
        else:
            code = "RELEASE_ELIGIBLE"
        return ReleaseEligibility(request.artifact_id, eligible, code, approved, pending, rejected, changes)

    def mission_control_queue(self) -> tuple[dict[str, object], ...]:
        output = []
        for request_id in sorted(self.requests):
            eligibility = self.eligibility(request_id)
            output.append({
                "request_id": request_id,
                "artifact_id": eligibility.artifact_id,
                "eligible": eligibility.eligible,
                "code": eligibility.code,
                "pending_classes": list(eligibility.pending_classes),
                "rejected_classes": list(eligibility.rejected_classes),
                "changes_requested_classes": list(eligibility.changes_requested_classes),
            })
        return tuple(output)

    def require_request(self, request_id: str) -> ReviewRequest:
        try:
            return self.requests[request_id]
        except KeyError as exc:
            raise LookupError("REVIEW_REQUEST_NOT_FOUND") from exc
