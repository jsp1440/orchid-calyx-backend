"""BUILD-034 Constitutional Mission Orchestrator.

This module is the first implementation of Calyx constitutional autonomy. It is
planning and governance infrastructure only: it evaluates proposed missions,
assigns autonomy levels, records decision metadata, and identifies governance
questions. It does not perform unsafe writes or deployments.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class AutonomyLevel(str, Enum):
    OBSERVE = "level_0_observe"
    SAFE_OPERATIONS = "level_1_safe_operations"
    PROPOSE = "level_2_propose"
    TRUSTED_EXECUTION = "level_3_trusted_execution"
    OWNER_APPROVAL = "level_4_owner_approval_required"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ConstitutionalPolicy:
    policy_key: str
    title: str
    description: str
    autonomy_level: AutonomyLevel
    risk_level: RiskLevel
    constitutional_articles: list[str]
    required_evidence: list[str]
    rollback_required: bool


@dataclass(frozen=True)
class MissionProposal:
    mission_key: str
    title: str
    domain: str
    objective: str
    proposed_action: str
    evidence: list[str] = field(default_factory=list)
    requested_autonomy_level: AutonomyLevel = AutonomyLevel.PROPOSE
    reversible: bool = True
    touches_production: bool = False
    touches_schema: bool = False
    touches_security: bool = False
    deletes_data: bool = False
    changes_constitution: bool = False


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    timestamp: str
    build: str
    mission_key: str
    mission_title: str
    domain: str
    decision: str
    autonomy_level: AutonomyLevel
    risk_level: RiskLevel
    constitutional_articles: list[str]
    policies_used: list[str]
    evidence: list[str]
    confidence: float
    rationale: str
    rollback_checkpoint: str | None
    next_recommended_action: str
    owner_review_required: bool


@dataclass(frozen=True)
class GovernanceQuestion:
    question_id: str
    timestamp: str
    mission_key: str
    question: str
    reason: str
    recommended_owner_action: str


class ConstitutionalKernel:
    """Evaluate Calyx missions against BUILD-031 constitutional principles."""

    build = "BUILD-034"

    def __init__(self) -> None:
        self.policies = self._default_policies()

    def _default_policies(self) -> dict[str, ConstitutionalPolicy]:
        policies = [
            ConstitutionalPolicy(
                policy_key="preserve_provenance",
                title="Preserve provenance",
                description="Claims, decisions, and generated work must remain traceable to sources or explicit rationale.",
                autonomy_level=AutonomyLevel.SAFE_OPERATIONS,
                risk_level=RiskLevel.LOW,
                constitutional_articles=["Article II — Relationships", "Article IV — Ways of Knowing", "Article IX — Calyx"],
                required_evidence=["source references", "decision rationale"],
                rollback_required=True,
            ),
            ConstitutionalPolicy(
                policy_key="prefer_reversible_work",
                title="Prefer reversible work",
                description="Autonomous work should produce reversible artifacts, plans, reports, queues, or branches before irreversible actions.",
                autonomy_level=AutonomyLevel.PROPOSE,
                risk_level=RiskLevel.LOW,
                constitutional_articles=["Article VIII — Evolution", "Article X — The Living Graph"],
                required_evidence=["rollback checkpoint", "artifact path or branch"],
                rollback_required=True,
            ),
            ConstitutionalPolicy(
                policy_key="owner_approval_for_high_risk",
                title="Owner approval for high-risk changes",
                description="Deployments, authentication, security, destructive actions, schema changes, and constitutional changes require owner review.",
                autonomy_level=AutonomyLevel.OWNER_APPROVAL,
                risk_level=RiskLevel.HIGH,
                constitutional_articles=["Article IX — Calyx", "Article XI — The Observer"],
                required_evidence=["owner approval", "risk assessment", "rollback plan"],
                rollback_required=True,
            ),
            ConstitutionalPolicy(
                policy_key="advance_relationships",
                title="Advance relationship visibility",
                description="Work should help reveal relationships among organisms, evidence, people, learning, conservation, or systems.",
                autonomy_level=AutonomyLevel.SAFE_OPERATIONS,
                risk_level=RiskLevel.LOW,
                constitutional_articles=["Article I — The Continuum", "Article II — Relationships", "Article XII — Emergence"],
                required_evidence=["relationship revealed or strengthened"],
                rollback_required=False,
            ),
        ]
        return {policy.policy_key: policy for policy in policies}

    def evaluate(self, proposal: MissionProposal) -> dict[str, Any]:
        risk = self._risk_for(proposal)
        autonomy = self._autonomy_for(proposal, risk)
        policies_used = self._policies_for(proposal, risk)
        owner_review_required = autonomy == AutonomyLevel.OWNER_APPROVAL
        governance_questions = self._governance_questions_for(proposal, risk)
        decision = "blocked_pending_owner_review" if owner_review_required else "approved_for_delegated_progress"
        confidence = self._confidence_for(proposal, governance_questions)
        checkpoint = self._checkpoint_for(proposal) if proposal.reversible else None

        record = DecisionRecord(
            decision_id=f"DEC-{uuid4().hex[:12].upper()}",
            timestamp=self._now(),
            build=self.build,
            mission_key=proposal.mission_key,
            mission_title=proposal.title,
            domain=proposal.domain,
            decision=decision,
            autonomy_level=autonomy,
            risk_level=risk,
            constitutional_articles=sorted({article for policy in policies_used for article in policy.constitutional_articles}),
            policies_used=[policy.policy_key for policy in policies_used],
            evidence=proposal.evidence,
            confidence=confidence,
            rationale=self._rationale_for(proposal, risk, autonomy),
            rollback_checkpoint=checkpoint,
            next_recommended_action=self._next_action_for(proposal, autonomy),
            owner_review_required=owner_review_required,
        )

        return {
            "build": self.build,
            "status": "constitutional_review_complete",
            "decision_record": asdict(record),
            "governance_questions": [asdict(question) for question in governance_questions],
            "policy_snapshot": [asdict(policy) for policy in self.policies.values()],
        }

    def mission_registry(self) -> dict[str, Any]:
        missions = [
            {"mission_key": "engineering", "title": "Engineering", "priority": 98, "status": "active", "next_action": "repair homepage and wire Mission Control"},
            {"mission_key": "science", "title": "Science", "priority": 96, "status": "active", "next_action": "expand literature and relationship extraction"},
            {"mission_key": "conservation", "title": "Conservation", "priority": 94, "status": "active", "next_action": "connect habitat, threat, pollinator, and mycorrhizal signals"},
            {"mission_key": "education", "title": "Education", "priority": 90, "status": "active", "next_action": "build glossary and Orchid University learning pathways"},
            {"mission_key": "funding", "title": "Funding", "priority": 99, "status": "urgent", "next_action": "prepare grant-ready evidence and narrative package"},
            {"mission_key": "community", "title": "Community", "priority": 86, "status": "planned", "next_action": "prepare OASIS and citizen-science contribution loops"},
            {"mission_key": "infrastructure", "title": "Infrastructure", "priority": 92, "status": "active", "next_action": "stabilize runtime, connectors, telemetry, and deployment checks"},
        ]
        return {
            "build": self.build,
            "status": "mission_registry_ready",
            "missions": missions,
            "recommended_next_mission": max(missions, key=lambda row: row["priority"]),
            "timestamp": self._now(),
        }

    def _risk_for(self, proposal: MissionProposal) -> RiskLevel:
        if proposal.changes_constitution or proposal.touches_security or proposal.deletes_data:
            return RiskLevel.HIGH
        if proposal.touches_schema or proposal.touches_production:
            return RiskLevel.HIGH
        if not proposal.reversible:
            return RiskLevel.MEDIUM
        if proposal.requested_autonomy_level == AutonomyLevel.TRUSTED_EXECUTION:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _autonomy_for(self, proposal: MissionProposal, risk: RiskLevel) -> AutonomyLevel:
        if risk == RiskLevel.HIGH:
            return AutonomyLevel.OWNER_APPROVAL
        if risk == RiskLevel.MEDIUM:
            return min(proposal.requested_autonomy_level, AutonomyLevel.PROPOSE, key=list(AutonomyLevel).index)
        return proposal.requested_autonomy_level

    def _policies_for(self, proposal: MissionProposal, risk: RiskLevel) -> list[ConstitutionalPolicy]:
        keys = ["preserve_provenance", "advance_relationships", "prefer_reversible_work"]
        if risk == RiskLevel.HIGH:
            keys.append("owner_approval_for_high_risk")
        return [self.policies[key] for key in keys]

    def _governance_questions_for(self, proposal: MissionProposal, risk: RiskLevel) -> list[GovernanceQuestion]:
        questions: list[GovernanceQuestion] = []
        if risk == RiskLevel.HIGH:
            questions.append(
                GovernanceQuestion(
                    question_id=f"GQ-{uuid4().hex[:10].upper()}",
                    timestamp=self._now(),
                    mission_key=proposal.mission_key,
                    question="Should Calyx proceed with a high-risk action or stop for owner approval?",
                    reason="The proposal touches production, schema, security, data deletion, or constitutional authority.",
                    recommended_owner_action="Review the decision record, confirm rollback plan, and explicitly approve or redirect.",
                )
            )
        if len(proposal.evidence) == 0:
            questions.append(
                GovernanceQuestion(
                    question_id=f"GQ-{uuid4().hex[:10].upper()}",
                    timestamp=self._now(),
                    mission_key=proposal.mission_key,
                    question="Is there enough evidence to justify this mission?",
                    reason="The proposal did not include supporting evidence or source references.",
                    recommended_owner_action="Add evidence or restrict the mission to observation/planning mode.",
                )
            )
        return questions

    def _confidence_for(self, proposal: MissionProposal, questions: list[GovernanceQuestion]) -> float:
        base = 0.82 if proposal.evidence else 0.62
        return max(0.35, base - (0.12 * len(questions)))

    def _rationale_for(self, proposal: MissionProposal, risk: RiskLevel, autonomy: AutonomyLevel) -> str:
        return (
            f"Mission '{proposal.title}' was evaluated under BUILD-031 constitutional principles. "
            f"Risk was classified as {risk.value}; delegated authority resolved to {autonomy.value}. "
            "Calyx may optimize execution, but it may not rewrite purpose."
        )

    def _next_action_for(self, proposal: MissionProposal, autonomy: AutonomyLevel) -> str:
        if autonomy == AutonomyLevel.OWNER_APPROVAL:
            return "Stop and request owner approval before execution."
        if autonomy == AutonomyLevel.PROPOSE:
            return "Prepare a reviewable plan, artifact, branch, or pull request without unsafe execution."
        if autonomy == AutonomyLevel.SAFE_OPERATIONS:
            return "Execute safe reversible work and write a decision record."
        return "Proceed within delegated authority and record checkpoint."

    def _checkpoint_for(self, proposal: MissionProposal) -> str:
        return f"CP-{proposal.mission_key.upper()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
