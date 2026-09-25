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
_STATE_SCHEMA = "oc.calyx-closed-loop-state.v1"


def run_closed_loop_cycle(
    *,
    intents: list[DevelopmentIntent],
    snapshot: dict[str, Any],
    execution_evidence: list[ExecutionEvidencePacket] | None = None,
    reserve_depth: int = 1,
    planner_ok: bool = True,
    persisted_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one deterministic control cycle without granting action authority."""
    state = persisted_state or {}
    if state and state.get("schema") != _STATE_SCHEMA:
        raise ValueError("CALYX_CLOSED_LOOP_STATE_SCHEMA_INVALID")
    seen_raw = state.get("seen_feedback_fingerprints", [])
    completed_raw = state.get("completed_semantic_keys", [])
    if not isinstance(seen_raw, list) or not all(isinstance(item, str) for item in seen_raw):
        raise TypeError("CALYX_CLOSED_LOOP_SEEN_FEEDBACK_INVALID")
    if not isinstance(completed_raw, list) or not all(
        isinstance(item, str) for item in completed_raw
    ):
        raise TypeError("CALYX_CLOSED_LOOP_COMPLETED_KEYS_INVALID")
    seen_feedback = set(seen_raw)
    completed_semantic_keys = set(completed_raw)

    feedback = [
        classify_execution_evidence(packet)
        for packet in (execution_evidence or [])
    ]

    completed_source_keys = {
        item["source_key"] for item in feedback if item["disposition"] == "COMPLETE"
    }
    completed_semantic_keys.update(
        f'calyx-director:{source_key}' for source_key in completed_source_keys
    )
    active_intents = [
        intent
        for intent in intents
        if f"calyx-director:{intent.source_key}" not in completed_semantic_keys
    ]

    refill = plan_calyx_refill(
        active_intents,
        snapshot,
        reserve_depth=reserve_depth,
        planner_ok=planner_ok,
    )

    revisions = [
        item
        for item in feedback
        if item["disposition"] == "REVISE" and item["fingerprint"] not in seen_feedback
    ]
    seen_feedback.update(item["fingerprint"] for item in feedback)
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
        "persisted_state": {
            "schema": _STATE_SCHEMA,
            "seen_feedback_fingerprints": sorted(seen_feedback),
            "completed_semantic_keys": sorted(completed_semantic_keys),
        },
    }
