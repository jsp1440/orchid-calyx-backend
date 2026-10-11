"""FIL-001 Functional Interaction Layer prototype (read-only, dry-run only).

Describes existing functions with versioned input/output/precondition/effect
contracts, checks functional-edge compatibility, plans workflows and runs
deterministic dry runs over fixtures. It adds no scheduler, queue, registry of
record or execution authority; see ``docs/fil/FIL-001.md``.
"""

from .compatibility import FunctionalEdge, check_edge
from .contracts import (
    AutonomyClass,
    BudgetRequirement,
    CapabilityDescriptor,
    ContractError,
    HealthSpec,
    OperatorClass,
    PortSpec,
    ProvenanceRequirement,
)
from .dry_run import DryRunReport, FunctionalReceipt, HandlerResult, execute_dry_run
from .governance import GovernanceAction, GovernanceDecision, evaluate_plan
from .planner import SourceArtifact, WorkflowPlan, plan_workflow
from .registry import FunctionalRegistry

__all__ = [
    "AutonomyClass",
    "BudgetRequirement",
    "CapabilityDescriptor",
    "ContractError",
    "DryRunReport",
    "FunctionalEdge",
    "FunctionalReceipt",
    "FunctionalRegistry",
    "GovernanceAction",
    "GovernanceDecision",
    "HandlerResult",
    "HealthSpec",
    "OperatorClass",
    "PortSpec",
    "ProvenanceRequirement",
    "SourceArtifact",
    "WorkflowPlan",
    "check_edge",
    "evaluate_plan",
    "execute_dry_run",
    "plan_workflow",
]
