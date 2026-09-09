from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .specialist_models import (
    SpecialistApproval,
    SpecialistArtifact,
    SpecialistMission,
    SpecialistReview,
)

COORDINATOR = "calyx-executive"
REVIEWER = "scientific-reviewer"
KNOWN_SPECIALISTS = {
    "taxonomist-botanist",
    "evidence-scientist",
    "quantitative-scientist",
    "conservation-specialist",
    "education-specialist",
    "experience-designer",
    "data-steward",
}
ROUTES: dict[str, list[str]] = {
    "taxonomy": ["taxonomist-botanist", "data-steward"],
    "species-profile": ["taxonomist-botanist", "evidence-scientist"],
    "trait-analysis": ["taxonomist-botanist", "evidence-scientist"],
    "cultivation": ["taxonomist-botanist", "evidence-scientist"],
    "identification": ["taxonomist-botanist", "evidence-scientist"],
    "research": ["evidence-scientist"],
    "evidence-review": ["evidence-scientist"],
    "literature": ["evidence-scientist"],
    "analysis": ["quantitative-scientist", "evidence-scientist"],
    "statistics": ["quantitative-scientist"],
    "geography": ["quantitative-scientist", "data-steward"],
    "modeling": ["quantitative-scientist", "evidence-scientist"],
    "conservation": ["conservation-specialist", "evidence-scientist"],
    "climate": ["conservation-specialist", "quantitative-scientist"],
    "lesson": ["education-specialist", "taxonomist-botanist"],
    "classroom": ["education-specialist", "taxonomist-botanist"],
    "interface": ["experience-designer"],
    "presentation": ["experience-designer", "education-specialist"],
    "harvest": ["data-steward"],
    "enrichment": ["data-steward"],
    "data-quality": ["data-steward"],
    "general-research": ["evidence-scientist"],
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def plan_activation(kind: str, *, scientific: bool, publication_candidate: bool, max_specialists: int) -> dict:
    if kind not in ROUTES:
        raise ValueError("MISSION_KIND_NOT_ALLOWED")
    cap = max(1, min(max_specialists, 7))
    specialists = ROUTES[kind][:cap]
    return {
        "registry_version": "1.0.0",
        "coordinator": COORDINATOR,
        "specialists": specialists,
        "reviewer": REVIEWER if scientific or publication_candidate else None,
        "owner_approval_required": bool(publication_candidate),
        "automatic_publication": False,
    }


@dataclass(frozen=True)
class MissionSpec:
    idempotency_key: str
    kind: str
    question: str
    scientific: bool = True
    publication_candidate: bool = False
    max_specialists: int = 4
    token_budget: int = 100000
    cost_budget_microusd: int = 0
    constraints: dict[str, Any] | None = None


class SpecialistMissionRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, *, owner: str, spec: MissionSpec) -> SpecialistMission:
        request = {
            "kind": spec.kind,
            "question": spec.question,
            "scientific": spec.scientific,
            "publication_candidate": spec.publication_candidate,
            "max_specialists": spec.max_specialists,
            "token_budget": spec.token_budget,
            "cost_budget_microusd": spec.cost_budget_microusd,
            "constraints": spec.constraints or {},
        }
        request_fingerprint = fingerprint(request)
        existing = self.db.scalar(
            select(SpecialistMission).where(
                SpecialistMission.owner == owner,
                SpecialistMission.idempotency_key == spec.idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_fingerprint != request_fingerprint:
                raise ValueError("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST")
            return existing

        activation = plan_activation(
            spec.kind,
            scientific=spec.scientific,
            publication_candidate=spec.publication_candidate,
            max_specialists=spec.max_specialists,
        )
        mission = SpecialistMission(
            owner=owner,
            idempotency_key=spec.idempotency_key,
            request_fingerprint=request_fingerprint,
            kind=spec.kind,
            question=spec.question,
            status="active",
            scientific=spec.scientific,
            publication_candidate=spec.publication_candidate,
            automatic_publication=False,
            owner_approval_required=activation["owner_approval_required"],
            max_specialists=spec.max_specialists,
            token_budget=spec.token_budget,
            cost_budget_microusd=spec.cost_budget_microusd,
            activation_json=canonical_json(activation),
            constraints_json=canonical_json(spec.constraints or {}),
        )
        self.db.add(mission)
        self.db.commit()
        self.db.refresh(mission)
        return mission

    def owned(self, *, owner: str, mission_id: str) -> SpecialistMission:
        mission = self.db.get(SpecialistMission, mission_id)
        if mission is None or mission.owner != owner:
            raise LookupError("SPECIALIST_MISSION_NOT_FOUND")
        return mission

    def add_artifact(
        self,
        *,
        owner: str,
        mission_id: str,
        artifact_key: str,
        specialist_id: str,
        artifact_type: str,
        content: dict[str, Any],
        provenance: dict[str, Any],
        tokens_used: int = 0,
        cost_microusd: int = 0,
    ) -> SpecialistArtifact:
        mission = self.owned(owner=owner, mission_id=mission_id)
        activation = json.loads(mission.activation_json)
        allowed = set(activation["specialists"]) | {activation["coordinator"], activation.get("reviewer")}
        if specialist_id not in allowed or specialist_id not in KNOWN_SPECIALISTS | {COORDINATOR, REVIEWER}:
            raise ValueError("SPECIALIST_NOT_ACTIVATED")
        if not provenance:
            raise ValueError("PROVENANCE_REQUIRED")
        existing = self.db.scalar(
            select(SpecialistArtifact).where(
                SpecialistArtifact.mission_id == mission_id,
                SpecialistArtifact.artifact_key == artifact_key,
            )
        )
        artifact_payload = {
            "specialist_id": specialist_id,
            "artifact_type": artifact_type,
            "content": content,
            "provenance": provenance,
            "tokens_used": tokens_used,
            "cost_microusd": cost_microusd,
        }
        if existing is not None:
            existing_payload = {
                "specialist_id": existing.specialist_id,
                "artifact_type": existing.artifact_type,
                "content": json.loads(existing.content_json),
                "provenance": json.loads(existing.provenance_json),
                "tokens_used": existing.tokens_used,
                "cost_microusd": existing.cost_microusd,
            }
            if fingerprint(existing_payload) != fingerprint(artifact_payload):
                raise ValueError("ARTIFACT_KEY_REUSED_WITH_DIFFERENT_CONTENT")
            return existing
        if mission.tokens_used + tokens_used > mission.token_budget:
            raise ValueError("TOKEN_BUDGET_EXCEEDED")
        if mission.cost_budget_microusd and mission.cost_used_microusd + cost_microusd > mission.cost_budget_microusd:
            raise ValueError("COST_BUDGET_EXCEEDED")
        artifact = SpecialistArtifact(
            mission_id=mission_id,
            artifact_key=artifact_key,
            specialist_id=specialist_id,
            artifact_type=artifact_type,
            content_json=canonical_json(content),
            provenance_json=canonical_json(provenance),
            tokens_used=tokens_used,
            cost_microusd=cost_microusd,
        )
        mission.tokens_used += tokens_used
        mission.cost_used_microusd += cost_microusd
        self.db.add(artifact)
        self.db.commit()
        self.db.refresh(artifact)
        return artifact

    def record_review(
        self,
        *,
        owner: str,
        mission_id: str,
        review_key: str,
        reviewer_id: str,
        passed: bool,
        findings: dict[str, Any],
        provenance: dict[str, Any],
    ) -> SpecialistReview:
        mission = self.owned(owner=owner, mission_id=mission_id)
        activation = json.loads(mission.activation_json)
        if activation.get("reviewer") != REVIEWER or reviewer_id != REVIEWER:
            raise ValueError("INDEPENDENT_SCIENTIFIC_REVIEWER_REQUIRED")
        if not provenance:
            raise ValueError("PROVENANCE_REQUIRED")
        existing = self.db.scalar(
            select(SpecialistReview).where(
                SpecialistReview.mission_id == mission_id,
                SpecialistReview.review_key == review_key,
            )
        )
        if existing is not None:
            return existing
        review = SpecialistReview(
            mission_id=mission_id,
            review_key=review_key,
            reviewer_id=reviewer_id,
            passed=passed,
            findings_json=canonical_json(findings),
            provenance_json=canonical_json(provenance),
        )
        mission.status = "review_passed" if passed else "review_blocked"
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        return review

    def record_approval(
        self,
        *,
        owner: str,
        mission_id: str,
        approval_key: str,
        actor: str,
        decision: str,
        note: str | None,
    ) -> SpecialistApproval:
        mission = self.owned(owner=owner, mission_id=mission_id)
        if actor != owner:
            raise PermissionError("OWNER_APPROVAL_ACTOR_MISMATCH")
        if decision not in {"approved", "rejected"}:
            raise ValueError("APPROVAL_DECISION_NOT_ALLOWED")
        existing = self.db.scalar(
            select(SpecialistApproval).where(
                SpecialistApproval.mission_id == mission_id,
                SpecialistApproval.approval_key == approval_key,
            )
        )
        if existing is not None:
            return existing
        approval = SpecialistApproval(
            mission_id=mission_id,
            approval_key=approval_key,
            actor=actor,
            decision=decision,
            note=note,
        )
        mission.status = "owner_approved" if decision == "approved" else "owner_rejected"
        self.db.add(approval)
        self.db.commit()
        self.db.refresh(approval)
        return approval

    def snapshot(self, *, owner: str, mission_id: str) -> dict:
        mission = self.owned(owner=owner, mission_id=mission_id)
        artifacts = list(self.db.scalars(select(SpecialistArtifact).where(SpecialistArtifact.mission_id == mission_id)))
        reviews = list(self.db.scalars(select(SpecialistReview).where(SpecialistReview.mission_id == mission_id)))
        approvals = list(self.db.scalars(select(SpecialistApproval).where(SpecialistApproval.mission_id == mission_id)))
        review_passed = any(review.passed for review in reviews)
        owner_approved = any(approval.decision == "approved" for approval in approvals)
        promotion_eligible = bool(
            review_passed and (not mission.owner_approval_required or owner_approved)
        )
        return {
            "mission_id": mission.mission_id,
            "kind": mission.kind,
            "question": mission.question,
            "status": mission.status,
            "scientific": mission.scientific,
            "publication_candidate": mission.publication_candidate,
            "activation": json.loads(mission.activation_json),
            "budget": {
                "tokens": {"used": mission.tokens_used, "limit": mission.token_budget},
                "cost_microusd": {"used": mission.cost_used_microusd, "limit": mission.cost_budget_microusd},
            },
            "artifact_count": len(artifacts),
            "review_count": len(reviews),
            "approval_count": len(approvals),
            "promotion": {
                "eligible": promotion_eligible,
                "automatic_publication": False,
                "review_passed": review_passed,
                "owner_approved": owner_approved,
            },
        }
