"""FIL-001B: declare a FIL plan to the existing work router, without a new queue.

The swarm already routes work by markers in an issue body
(``OC-SWARM-CAPABILITY``; see ``app.provider_reservoir.routing``). A FIL plan
can be expressed in exactly that vocabulary, so the existing router -- not FIL
-- decides how it is classified and whether any lane may take it.

This module renders the markers and asks the router. It creates no issue,
claims no lease, labels nothing and schedules nothing.
"""

from __future__ import annotations

from typing import Any

from app.provider_reservoir.routing import route_task

from .planner import WorkflowPlan

MARKER = "OC-SWARM-CAPABILITY"


def declaration_body(plan: WorkflowPlan) -> str:
    """Issue-body lines declaring every canonical capability the plan uses."""
    if not plan.found:
        raise ValueError("NO_PLAN_TO_DECLARE")
    names = sorted({step.registry_capability for step in plan.steps})
    lines = [f"FIL plan {plan.plan_id} ({len(plan.steps)} steps)."]
    lines += [f"{MARKER}: {name}" for name in names]
    return "\n".join(lines) + "\n"


def route_plan(plan: WorkflowPlan, *, issue_number: int = 0) -> dict[str, Any]:
    """What the existing router says about this plan, verbatim."""
    routing = route_task({"number": issue_number, "body": declaration_body(plan)})
    return {
        "plan_id": plan.plan_id,
        "declared_capabilities": sorted(
            {step.registry_capability for step in plan.steps}
        ),
        "deterministic_capabilities": list(routing.deterministic_capabilities),
        "blocking_provider_capabilities": list(routing.blocking_provider_capabilities),
        "provider_free": routing.provider_free,
        "lane_executable": routing.lane_executable,
        "unexecutable_reason": routing.unexecutable_reason,
        "reasons": list(routing.reasons),
        "issue_created": False,
        "lease_claimed": False,
    }
