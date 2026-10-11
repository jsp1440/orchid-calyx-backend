"""Governance verdict for a FIL workflow plan.

FIL-001 can authorize exactly one thing: a deterministic dry run of a plan in
which every step is safe-autonomous, provider-free, implemented, and free of
prohibited permissions. Everything else fails closed to the existing boundary
it touches -- provider work parks (NO-API), approval-class work goes to the
owner, prohibited work is refused. Production execution is never available
here; that decision belongs to the factory policy and the owner.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.calyx_orchestrator.executor import PROHIBITED_CAPABILITIES
from app.provider_reservoir.capabilities import classify_capabilities

from .contracts import DRY_RUN_EXECUTABLE_STATUSES, AutonomyClass
from .planner import WorkflowPlan

DRY_RUN_MODE = "dry_run"

#: Plan-level cost ceiling for one dry run, in the agent security gateway's
#: cost units (``GatewayPolicy.max_total_cost_units`` defaults to the same 25).
MAX_DRY_RUN_COST_UNITS = 25


class GovernanceAction(StrEnum):
    ALLOW_DRY_RUN = "allow_dry_run"
    PARK_PROVIDER_REQUIRED = "park_provider_required"
    OWNER_GATE = "owner_gate"
    REFUSE = "refuse"


_PRECEDENCE = {
    GovernanceAction.ALLOW_DRY_RUN: 0,
    GovernanceAction.PARK_PROVIDER_REQUIRED: 1,
    GovernanceAction.OWNER_GATE: 2,
    GovernanceAction.REFUSE: 3,
}

#: Authorities FIL-001 never grants, stated on every decision so a reader of a
#: stored decision cannot mistake an ALLOW for more than it is.
WITHHELD_AUTHORITY = {
    "production_execution_authorized": False,
    "scientific_publication_authorized": False,
    "knowledge_promotion_authorized": False,
    "taxonomy_activation_authorized": False,
    "production_mutation_authorized": False,
    "provider_spend_authorized": False,
    "integration_authorized": False,
}


@dataclass(frozen=True)
class GovernanceDecision:
    plan_id: str
    mode: str
    action: GovernanceAction
    reasons: tuple[str, ...]

    @property
    def dry_run_authorized(self) -> bool:
        return self.action is GovernanceAction.ALLOW_DRY_RUN

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "oc.fil.governance-decision.v1",
            "plan_id": self.plan_id,
            "mode": self.mode,
            "action": self.action.value,
            "reasons": list(self.reasons),
            "dry_run_authorized": self.dry_run_authorized,
            **WITHHELD_AUTHORITY,
        }


def evaluate_plan(
    plan: WorkflowPlan, *, mode: str = DRY_RUN_MODE, no_api_mode: bool = True
) -> GovernanceDecision:
    findings: list[tuple[GovernanceAction, str]] = []

    if mode != DRY_RUN_MODE:
        findings.append(
            (GovernanceAction.OWNER_GATE, f"FIL_001_HAS_NO_AUTHORITY_FOR_MODE:{mode}")
        )
    if not plan.found:
        findings.append((GovernanceAction.REFUSE, "NO_COMPATIBLE_PLAN"))
    if plan.source_edge is not None and not plan.source_edge.compatible:
        findings.append((GovernanceAction.REFUSE, "SOURCE_EDGE_INCOMPATIBLE"))
    for edge in plan.edges:
        if not edge.compatible:
            findings.append(
                (GovernanceAction.REFUSE, f"EDGE_INCOMPATIBLE:{edge.edge_id}")
            )

    _, provider = classify_capabilities(
        [step.registry_capability for step in plan.steps]
    )
    for name in provider:
        if no_api_mode:
            findings.append(
                (
                    GovernanceAction.PARK_PROVIDER_REQUIRED,
                    f"NO_API_PROVIDER_CAPABILITY:{name}",
                )
            )
        else:
            findings.append(
                (
                    GovernanceAction.OWNER_GATE,
                    f"PROVIDER_SPEND_NOT_AUTHORIZED_BY_FIL:{name}",
                )
            )

    cost_units = 0
    for step in plan.steps:
        cost_units += step.budget.cost_units_max
        if step.autonomy_class is AutonomyClass.PROHIBITED:
            findings.append(
                (GovernanceAction.REFUSE, f"AUTONOMY_CLASS_D:{step.capability_id}")
            )
        elif step.autonomy_class is AutonomyClass.HUMAN_APPROVAL:
            findings.append(
                (GovernanceAction.OWNER_GATE, f"AUTONOMY_CLASS_B:{step.capability_id}")
            )
        elif step.autonomy_class is AutonomyClass.PROPOSAL_ONLY:
            findings.append(
                (
                    GovernanceAction.OWNER_GATE,
                    f"AUTONOMY_CLASS_C_PROPOSAL_ONLY:{step.capability_id}",
                )
            )
        prohibited = sorted(set(step.permissions) & PROHIBITED_CAPABILITIES)
        if prohibited:
            findings.append(
                (
                    GovernanceAction.REFUSE,
                    f"PROHIBITED_PERMISSION:{step.capability_id}:{','.join(prohibited)}",
                )
            )
        if step.health.status not in DRY_RUN_EXECUTABLE_STATUSES:
            findings.append(
                (
                    GovernanceAction.REFUSE,
                    f"NOT_EXECUTABLE:{step.capability_id}:{step.health.status}",
                )
            )
        if step.budget.provider_calls_max:
            findings.append(
                (
                    GovernanceAction.PARK_PROVIDER_REQUIRED,
                    f"PROVIDER_CALL_BUDGET:{step.capability_id}",
                )
            )
    if cost_units > MAX_DRY_RUN_COST_UNITS:
        findings.append(
            (
                GovernanceAction.REFUSE,
                f"COST_UNITS_EXCEEDED:{cost_units}>{MAX_DRY_RUN_COST_UNITS}",
            )
        )

    if not findings:
        return GovernanceDecision(
            plan.plan_id,
            mode,
            GovernanceAction.ALLOW_DRY_RUN,
            ("ALL_STEPS_SAFE_AUTONOMOUS",),
        )
    action = max((action for action, _ in findings), key=_PRECEDENCE.__getitem__)
    reasons = tuple(sorted({reason for _, reason in findings}))
    return GovernanceDecision(plan.plan_id, mode, action, reasons)
