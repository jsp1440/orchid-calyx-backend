"""Provider-free bridge from DeepOrchestrate leaves to reserve persistence.

Only READY leaves with an existing GitHub issue lineage may enter the shared
reserve planner. The bridge does not launch a provider, create an issue, lease a
task, or expand authority.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.calyx_orchestrator.deep_orchestrate import DeepOrchestrate, TaskLeaf
from scripts.oc_backlog_refiller import plan_refill

_SCHEMA = "oc.deep-orchestrate-reserve-source.v1"


def _fingerprint(leaf: TaskLeaf) -> str:
    material = {
        "schema": _SCHEMA,
        "task_key": leaf.key,
        "issue_number": leaf.issue_number,
        "title": leaf.title,
        "repo": leaf.repo,
        "module": leaf.module,
        "priority": int(leaf.priority),
        "authority_class": leaf.authority_class,
        "acceptance_criteria": list(leaf.acceptance_criteria),
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _candidate(leaf: TaskLeaf) -> dict[str, Any]:
    boundaries = ["governance"] if leaf.requires_owner_gate else []
    if leaf.consequence_risk.strip().casefold() == "high":
        boundaries.append("governance")
    return {
        "source_kind": "issue",
        "source_ref": f"#{leaf.issue_number}",
        "title": leaf.title,
        "material_fingerprint": _fingerprint(leaf),
        "semantic_key": f"deep-orchestrate:{leaf.key}",
        "priority": max(0, min(5, int(leaf.priority))),
        "dependencies": [],
        "protected_boundaries": sorted(set(boundaries)),
    }


def plan_deep_orchestrate_refill(
    orchestrator: DeepOrchestrate,
    snapshot: dict[str, Any],
    *,
    reserve_depth: int = 2,
    planner_ok: bool = True,
) -> dict[str, Any]:
    """Plan persistence for legitimate ready leaves without launching workers.

    DeepOrchestrate remains the dependency/state authority. A leaf without an
    existing issue number is suppressed rather than materialized as artificial
    backlog. The shared planner performs cross-cycle fingerprint and semantic
    deduplication against existing delivery state.
    """

    candidates: list[dict[str, Any]] = []
    source_rejections: list[dict[str, Any]] = []
    for leaf in orchestrator.ready_tasks():
        if leaf.issue_number is None:
            source_rejections.append(
                {"task_key": leaf.key, "reason": "missing_issue_lineage"}
            )
            continue
        candidates.append(_candidate(leaf))

    result = plan_refill(
        snapshot,
        candidates,
        reserve_depth=reserve_depth,
        planner_ok=planner_ok,
    )
    states: dict[str, int] = {}
    for task in orchestrator.to_dict().get("tasks", {}).values():
        state = str(task.get("state") or "unknown")
        states[state] = states.get(state, 0) + 1

    result.update(
        {
            "source_schema": _SCHEMA,
            "source_candidate_count": len(candidates),
            "source_rejections": source_rejections,
            "source_state_counts": dict(sorted(states.items())),
            "provider_launch_authorized": False,
            "no_api_mode": True,
        }
    )
    return result
