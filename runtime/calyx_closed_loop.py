"""Provider-free closed-loop controller joining Calyx, Queue Bridge and execution evidence.

The controller is deliberately narrow: it plans one governed refill from Calyx
intents and classifies returned execution evidence. It does not mutate GitHub,
launch providers, merge, deploy, publish, or override owner gates.
"""

from __future__ import annotations

from typing import Any

from runtime.calyx_execution_feedback import (
    ExecutionEvidencePacket,
    classify_execution_evidence,
)
from runtime.calyx_queue_director import DevelopmentIntent, plan_calyx_refill

_SCHEMA = "oc.calyx-closed-loop.v1"


def run_closed_loop_cycle(
    *,
    intents: list[DevelopmentIntent],
    snapshot: dict[str, Any],
    execution_evidence: list[ExecutionEvidencePacket] | None = None,
    reserve_depth: int = 1,
    planner_ok: bool = True,
) -> dict[str, Any]:
    """Run one deterministic control cycle without granting action authority."""
    feedback = [
        classify_execution_evidence(packet)
        for packet in (execution_evidence or [])
    ]

    completed_source_keys = {
        item["source_key"] for item in feedback if item["disposition"] == "COMPLETE"
    }
    active_intents = [
        intent for intent in intents if intent.source_key not in completed_source_keys
    ]

    refill = plan_calyx_refill(
        active_intents,
        snapshot,
        reserve_depth=reserve_depth,
        planner_ok=planner_ok,
    )

    revisions = [
        item for item in feedback if item["disposition"] == "REVISE"
    ]
    blocked = [
        item for item in feedback if item["disposition"] == "BLOCKED"
    ]
    owner_gated = [
        item for item in feedback if item["disposition"] == "OWNER_GATED"
    ]

    return {
        "schema": _SCHEMA,
        "feedback": feedback,
        "refill": refill,
        "completed_source_keys": sorted(completed_source_keys),
        "revision_requests": revisions,
        "blocked": blocked,
        "owner_gated": owner_gated,
        "provider_launch_authorized": False,
        "no_api_mode": True,
        "authority": "queue-bridge",
        "action_authorized": False,
    }
