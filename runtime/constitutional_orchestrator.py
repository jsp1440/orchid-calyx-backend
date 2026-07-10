"""BUILD-034 Constitutional Mission Orchestrator.

This module establishes the first implementation of Calyx constitutional
autonomy. It does not grant unsafe write authority. Instead it creates a
traceable policy evaluator, mission registry, decision ledger, and governance
question queue that future autonomous loops can use before taking action.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any
from uuid import uuid4


class AutonomyLevel(IntEnum):
    """Delegated authority levels for Calyx actions."""

    OBSERVE = 0
    SAFE_OPERATIONS = 1
    PROPOSE = 2
    TRUSTED_EXECUTION = 3
    OWNER_APPROVAL_REQUIRED = 4


@dataclass(frozen=True)
class ConstitutionalPolicy:
    policy_id: str
    title: str
    principle: str
    max_autonomy_level: AutonomyLevel
    requires_rollback: bool
    requires_provenance: bool
    protected: bool = False


@dataclass(frozen=True)
class MissionDefinition:
    mission_id: str
    title: str
    purpose: str
    success_criteria: list[str]
    safe_autonomy_level: AutonomyLevel
    active: bool = True


@dataclass
class DecisionRecord:
    decision_id: str
    mission_id: str
    action: str
    requested_autonomy_level: int
    approved_autonomy_level: int
    status: str
    risk_level: str
    confidence: float
    constitutional_policies: list[str]
    rationale: str
    rollback_checkpoint: str | None
    governance_question_id: str | None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class GovernanceQuestion:
    question_id: str
    mission_id: str
    question: str
    reason: str
    status: str = "open"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ConstitutionalMissionOrchestrator:
    """Constitutional guardrail engine for Calyx mission planning."""

    build = "BUILD-034"

    def __init__(self) -> None:
        self.policies = self._default_policies()
        self.missions = self._default_missions()
        self._decision_ledger: list[DecisionRecord] = []
        self._governance_questions: list[GovernanceQuestion] = []

    def status(self) -> dict[str, Any]:
        return {
            "build": self.build,
            "status": "constitutional_orchestrator_ready",
            "mode": "guarded_planning_no_unreviewed_writes",
            "policy_count": len(self.policies),
            "mission_count": len(self.missions),
            "decision_count": len(self._decision_ledger),
            "open_governance_questions": len([q for q in self._governance_questions if q.status == "open"]),
            "autonomy_levels": [
                {"level": int(level), "name": level.name.lower()} for level in AutonomyLevel
            ],
            "north_star": "The Orchid Continuum exists to cultivate understanding by revealing relationships.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def mission_registry(self) -> dict[str, Any]:
        return {
            "build": self.build,
            "status": "mission_registry_ready",
            "missions": [
                {**asdict(mission), "safe_autonomy_level": int(mission.safe_autonomy_level)}
                for mission in self.missions.values()
            ],
        }

    def policy_registry(self) -> dict[str, Any]:
        return {
            "build": self.build,
            "status": "policy_registry_ready",
            "policies": [
                {**asdict(policy), "max_autonomy_level": int(policy.max_autonomy_level)}
                for policy in self.policies.values()
            ],
        }

    def decision_ledger(self) -> dict[str, Any]:
        return {
            "build": self.build,
            "status": "decision_ledger_ready",
            "decisions": [asdict(record) for record in self._decision_ledger],
        }

    def governance_questions(self) -> dict[str, Any]:
        return {
            "build": self.build,
            "status": "governance_queue_ready",
            "questions": [asdict(question) for question in self._governance_questions],
        }

    def evaluate_action(
        self,
        *,
        mission_id: str,
        action: str,
        requested_autonomy_level: int,
        evidence: list[str] | None = None,
        reversible: bool = True,
        provenance_available: bool = True,
    ) -> dict[str, Any]:
        """Evaluate whether a proposed Calyx action is allowed by policy."""

        evidence = evidence or []
        mission = self.missions.get(mission_id)
        if mission is None:
            question = self._open_question(
                mission_id=mission_id,
                question=f"Unknown mission requested: {mission_id}",
                reason="Calyx cannot evaluate autonomy for an unregistered mission.",
            )
            record = self._record_decision(
                mission_id=mission_id,
                action=action,
                requested_autonomy_level=requested_autonomy_level,
                approved_autonomy_level=0,
                status="blocked_governance_question",
                risk_level="unknown",
                confidence=0.0,
                constitutional_policies=[],
                rationale="Mission is not registered; owner guidance required.",
                rollback_checkpoint=None,
                governance_question_id=question.question_id,
            )
            return {"decision": asdict(record), "governance_question": asdict(question)}

        applicable = self._policies_for_action(action)
        allowed_level = min([mission.safe_autonomy_level, *[p.max_autonomy_level for p in applicable]])
        approved_level = min(requested_autonomy_level, int(allowed_level))

        blockers: list[str] = []
        if any(policy.requires_rollback for policy in applicable) and not reversible:
            blockers.append("rollback_required")
        if any(policy.requires_provenance for policy in applicable) and not provenance_available:
            blockers.append("provenance_required")
        high_risk_policy_applies = any(policy.policy_id == "owner_approval_for_high_risk" for policy in applicable)
        if high_risk_policy_applies or requested_autonomy_level >= int(AutonomyLevel.OWNER_APPROVAL_REQUIRED):
            blockers.append("owner_approval_required")
        if not evidence and requested_autonomy_level > int(AutonomyLevel.OBSERVE):
            blockers.append("evidence_required")

        if blockers:
            question = self._open_question(
                mission_id=mission_id,
                question=f"Owner review required before action: {action}",
                reason=", ".join(blockers),
            )
            record = self._record_decision(
                mission_id=mission_id,
                action=action,
                requested_autonomy_level=requested_autonomy_level,
                approved_autonomy_level=min(approved_level, int(AutonomyLevel.PROPOSE)),
                status="review_required",
                risk_level="high" if high_risk_policy_applies or "owner_approval_required" in blockers else "medium",
                confidence=0.55,
                constitutional_policies=[policy.policy_id for policy in applicable],
                rationale="Action requires human review or additional evidence before execution.",
                rollback_checkpoint=self._checkpoint_id(mission_id) if reversible else None,
                governance_question_id=question.question_id,
            )
            return {"decision": asdict(record), "governance_question": asdict(question)}

        record = self._record_decision(
            mission_id=mission_id,
            action=action,
            requested_autonomy_level=requested_autonomy_level,
            approved_autonomy_level=approved_level,
            status="approved" if approved_level == requested_autonomy_level else "approved_limited",
            risk_level="low" if approved_level <= 2 else "medium",
            confidence=0.82 if evidence else 0.65,
            constitutional_policies=[policy.policy_id for policy in applicable],
            rationale="Action is within delegated authority and satisfies rollback/provenance requirements.",
            rollback_checkpoint=self._checkpoint_id(mission_id) if reversible else None,
            governance_question_id=None,
        )
        return {"decision": asdict(record)}

    def _policies_for_action(self, action: str) -> list[ConstitutionalPolicy]:
        lower = action.lower()
        policies = [self.policies["preserve_provenance"], self.policies["prefer_reversible_changes"]]
        if any(
            term in lower
            for term in [
                "deploy",
                "deployment",
                "schema",
                "delete",
                "destructive",
                "secret",
                "credential",
                "auth",
                "security",
                "external_send",
                "external send",
                "cross_repository",
                "cross-repository",
                "harvester_control:update_schedule",
                "harvester_control:propose_target_change",
                "harvester_control:approve_target_change",
                "harvester_control:reject_target_change",
                "harvester_control:retire",
                "harvester_control:restore",
            ]
        ):
            policies.append(self.policies["owner_approval_for_high_risk"])
        if any(term in lower for term in ["literature", "relationship", "pollinator", "mycorrhiza", "matrix"]):
            policies.append(self.policies["distinguish_evidence_from_inference"])
        if any(term in lower for term in ["homepage", "frontend", "university", "grant", "lesson"]):
            policies.append(self.policies["reveal_relationships"])
        return policies

    def _record_decision(self, **kwargs: Any) -> DecisionRecord:
        record = DecisionRecord(decision_id=f"DEC-{uuid4().hex[:10].upper()}", **kwargs)
        self._decision_ledger.insert(0, record)
        self._decision_ledger = self._decision_ledger[:200]
        return record

    def _open_question(self, mission_id: str, question: str, reason: str) -> GovernanceQuestion:
        item = GovernanceQuestion(
            question_id=f"GQ-{uuid4().hex[:10].upper()}",
            mission_id=mission_id,
            question=question,
            reason=reason,
        )
        self._governance_questions.insert(0, item)
        self._governance_questions = self._governance_questions[:200]
        return item

    def _checkpoint_id(self, mission_id: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"CP-{mission_id.upper()}-{timestamp}"

    def _default_policies(self) -> dict[str, ConstitutionalPolicy]:
        policies = [
            ConstitutionalPolicy(
                policy_id="preserve_provenance",
                title="Preserve provenance",
                principle="Claims, actions, and outputs must remain traceable to evidence or explicit directives.",
                max_autonomy_level=AutonomyLevel.TRUSTED_EXECUTION,
                requires_rollback=False,
                requires_provenance=True,
            ),
            ConstitutionalPolicy(
                policy_id="prefer_reversible_changes",
                title="Prefer reversible changes",
                principle="Autonomous work should preserve rollback points and avoid irreversible production changes.",
                max_autonomy_level=AutonomyLevel.TRUSTED_EXECUTION,
                requires_rollback=True,
                requires_provenance=False,
            ),
            ConstitutionalPolicy(
                policy_id="reveal_relationships",
                title="Reveal relationships",
                principle="Actions should strengthen the Continuum by helping people see meaningful connections.",
                max_autonomy_level=AutonomyLevel.TRUSTED_EXECUTION,
                requires_rollback=True,
                requires_provenance=True,
            ),
            ConstitutionalPolicy(
                policy_id="distinguish_evidence_from_inference",
                title="Distinguish evidence from inference",
                principle="Scientific outputs must distinguish established evidence, interpretation, hypothesis, and uncertainty.",
                max_autonomy_level=AutonomyLevel.PROPOSE,
                requires_rollback=True,
                requires_provenance=True,
            ),
            ConstitutionalPolicy(
                policy_id="owner_approval_for_high_risk",
                title="Owner approval for high-risk actions",
                principle="Deployments, schema changes, authentication, security, deletion, and constitutional changes require owner approval.",
                max_autonomy_level=AutonomyLevel.PROPOSE,
                requires_rollback=True,
                requires_provenance=True,
                protected=True,
            ),
        ]
        return {policy.policy_id: policy for policy in policies}

    def _default_missions(self) -> dict[str, MissionDefinition]:
        missions = [
            MissionDefinition(
                mission_id="engineering",
                title="Engineering Mission",
                purpose="Maintain and improve backend, frontend, connectors, deployment readiness, and Mission Control.",
                success_criteria=["Builds are documented", "PRs are reviewable", "Deployments remain verifiable"],
                safe_autonomy_level=AutonomyLevel.PROPOSE,
            ),
            MissionDefinition(
                mission_id="science",
                title="Science Mission",
                purpose="Advance literature extraction, relationship extraction, Matrix, taxonomy, pollinator, mycorrhizal, vision, and atlas integration.",
                success_criteria=["Claims have provenance", "Evidence and inference are separated", "Knowledge gaps are queued"],
                safe_autonomy_level=AutonomyLevel.PROPOSE,
            ),
            MissionDefinition(
                mission_id="education",
                title="Education Mission",
                purpose="Build Orchid University, glossary, lessons, quizzes, mind maps, and adaptive learning pathways.",
                success_criteria=["Learning paths support multiple modalities", "Lessons reveal relationships", "Content remains evidence-aligned"],
                safe_autonomy_level=AutonomyLevel.TRUSTED_EXECUTION,
            ),
            MissionDefinition(
                mission_id="conservation",
                title="Conservation Mission",
                purpose="Prioritize habitat protection, species risk, mapping, restoration, partner coordination, and stewardship outputs.",
                success_criteria=["Priorities are evidence-based", "Threats and uncertainty are visible", "Outputs support stewardship"],
                safe_autonomy_level=AutonomyLevel.PROPOSE,
            ),
            MissionDefinition(
                mission_id="funding",
                title="Funding Mission",
                purpose="Coordinate grants, budgets, evidence packets, partner letters, deadlines, and proposal materials.",
                success_criteria=["Grant packages cite project evidence", "Deadlines are tracked", "Narratives match funder priorities"],
                safe_autonomy_level=AutonomyLevel.PROPOSE,
            ),
            MissionDefinition(
                mission_id="community",
                title="Community Mission",
                purpose="Support growers, societies, citizen scientists, artists, teachers, students, and collaborators.",
                success_criteria=["Contributions are welcomed with provenance", "Roles are clear", "Community outputs enrich understanding"],
                safe_autonomy_level=AutonomyLevel.SAFE_OPERATIONS,
            ),
            MissionDefinition(
                mission_id="institutional_memory",
                title="Institutional Memory Mission",
                purpose="Preserve build history, decisions, founding principles, governance questions, and architectural precedent.",
                success_criteria=["Decisions are recorded", "Precedents are traceable", "Future contributors can understand why choices were made"],
                safe_autonomy_level=AutonomyLevel.TRUSTED_EXECUTION,
            ),
        ]
        return {mission.mission_id: mission for mission in missions}


orchestrator = ConstitutionalMissionOrchestrator()
