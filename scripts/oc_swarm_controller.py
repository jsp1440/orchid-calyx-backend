#!/usr/bin/env python3
"""Bounded parallel execution planner for the Orchid Continuum software factory.

Swarm v2 keeps the canonical queue, priority, durable-PR suppression and owner
gates, but replaces coarse one-worker-per-product-lane scheduling with explicit
resource locks. Independent tasks inside the same product lane may therefore run
concurrently when their read/write claims do not overlap.

This planner is pure: it does not call model providers, mutate GitHub, merge,
deploy, spend money, or cross owner gates.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from typing import Any

DEFAULT_WORKER_SLOTS = 8
MAX_WORKER_SLOTS = 12


def _load_sibling(module_name: str, filename: str):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"required swarm module unavailable: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bounded_slots(value: Any) -> int:
    try:
        slots = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("worker_slots must be an integer") from exc
    if slots < 1:
        raise ValueError("worker_slots must be >= 1")
    return min(slots, MAX_WORKER_SLOTS)


def _issue_index(snapshot: dict) -> dict[int, dict]:
    result: dict[int, dict] = {}
    for issue in snapshot.get("issues") or []:
        if issue.get("number") is not None:
            result[int(issue["number"])] = issue
    return result


def build_swarm_plan(snapshot: dict, *, worker_slots: int = DEFAULT_WORKER_SLOTS) -> dict:
    """Return a bounded resource-aware worker matrix from canonical portfolio state."""
    slots = _bounded_slots(worker_slots)
    scheduler = _load_sibling("oc_portfolio_scheduler", "oc_portfolio_scheduler.py")
    locks = _load_sibling("oc_swarm_resource_locks", "oc_swarm_resource_locks.py")

    canonical_input = dict(snapshot)
    # Ask the canonical scheduler for enough capacity that its ranking contains
    # every candidate we may need. Resource-lock selection happens below.
    canonical_input["max_active_lanes"] = slots
    canonical_input.pop("stabilization_issue", None)
    plan = scheduler.build_plan(canonical_input)

    issues = _issue_index(snapshot)
    active_rows = []
    for item in plan.get("active_lanes") or []:
        number = item.get("number")
        if number is None or int(number) not in issues:
            continue
        active_rows.append((issues[int(number)], str(item.get("lane_id") or "UNASSIGNED")))
    active_locks = locks.held_locks(active_rows)

    active_count = len(active_rows)
    capacity = max(0, slots - active_count)

    candidates = []
    malformed = []
    for ranked in plan.get("ranking") or []:
        number = ranked.get("number")
        if number is None or int(number) not in issues:
            malformed.append(ranked)
            continue
        candidates.append(
            (
                issues[int(number)],
                str(ranked.get("lane_id") or "UNASSIGNED"),
                ranked,
            )
        )
    if malformed:
        raise RuntimeError("canonical planner returned ranked item without matching issue")

    selected, lock_suppressed = locks.select_with_resource_locks(
        candidates,
        active_locks=active_locks,
        capacity=capacity,
    )

    workers = []
    for ordinal, item in enumerate(selected, start=1):
        workers.append(
            {
                "slot": ordinal,
                "issue_number": int(item["issue_number"]),
                "lane_id": str(item.get("lane_id") or "UNASSIGNED"),
                "priority": int(item.get("priority", 4)),
                "selection_reason": str(item.get("selection_reason") or "resource-aware-priority"),
                "repair": bool(item.get("repair")),
                "reads": list(item.get("reads") or []),
                "writes": list(item.get("writes") or []),
            }
        )

    return {
        "schema": "oc.swarm-plan.v2",
        "requested_worker_slots": int(worker_slots),
        "effective_worker_slots": slots,
        "active_worker_count": active_count,
        "available_capacity": capacity,
        "launch_count": len(workers),
        "workers": workers,
        "matrix": {"include": workers},
        "selected_numbers": [worker["issue_number"] for worker in workers],
        "active_resource_locks": active_locks,
        "resource_lock_suppressed": lock_suppressed,
        "canonical_suppressed": list(plan.get("suppressed") or []),
        "eligible_count": int(plan.get("eligible_count") or 0),
        "generated_at": plan.get("generated_at"),
        "safety": {
            "merge_to_main": False,
            "production_deploy": False,
            "provider_calls_in_planner": False,
            "owner_gates_preserved": True,
            "bounded": True,
            "resource_locking": True,
            "read_read_parallelism": True,
            "write_conflicts_fail_closed": True,
        },
    }


def _write_github_output(path: str, plan: dict) -> None:
    matrix = json.dumps(plan["matrix"], separators=(",", ":"))
    summary = json.dumps(plan, separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"matrix={matrix}\n")
        handle.write(f"launch_count={plan['launch_count']}\n")
        handle.write(f"selected_numbers={json.dumps(plan['selected_numbers'], separators=(',', ':'))}\n")
        handle.write(f"summary={summary}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="JSON snapshot path, or - for stdin")
    parser.add_argument("--worker-slots", type=int, default=DEFAULT_WORKER_SLOTS)
    parser.add_argument("--github-output", help="optional GITHUB_OUTPUT path")
    args = parser.parse_args(argv)

    if args.input == "-":
        snapshot = json.load(sys.stdin)
    else:
        with open(args.input, encoding="utf-8") as handle:
            snapshot = json.load(handle)

    plan = build_swarm_plan(snapshot, worker_slots=args.worker_slots)
    if args.github_output:
        _write_github_output(args.github_output, plan)
    json.dump(plan, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
