#!/usr/bin/env python3
"""Bounded parallel execution planner for the Orchid Continuum software factory.

This module turns the existing deterministic portfolio scheduler into a swarm
launch plan. It does not call model providers, mutate GitHub, merge code, deploy,
or cross owner gates. The GitHub Actions controller is responsible for taking
short-lived leases on the selected issues and invoking the existing completion
lane once per issue.

Design goals:
- bounded concurrency, never an unbounded fan-out;
- reuse the canonical queue/priority/durable-PR policy;
- one implementation worker per canonical product lane by default to reduce
  overlapping writes and merge-conflict storms;
- explicit machine-readable worker matrix and observability summary;
- fail closed when the canonical planner is unavailable or returns malformed
  output.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from typing import Any

DEFAULT_WORKER_SLOTS = 5
MAX_WORKER_SLOTS = 8


def _load_portfolio_scheduler():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "oc_portfolio_scheduler.py")
    spec = importlib.util.spec_from_file_location("oc_portfolio_scheduler", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("canonical portfolio scheduler unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "build_plan"):
        raise RuntimeError("canonical portfolio scheduler has no build_plan")
    return module


def _bounded_slots(value: Any) -> int:
    try:
        slots = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("worker_slots must be an integer") from exc
    if slots < 1:
        raise ValueError("worker_slots must be >= 1")
    return min(slots, MAX_WORKER_SLOTS)


def build_swarm_plan(snapshot: dict, *, worker_slots: int = DEFAULT_WORKER_SLOTS) -> dict:
    """Return a bounded worker matrix derived from the canonical portfolio plan."""
    slots = _bounded_slots(worker_slots)
    scheduler = _load_portfolio_scheduler()

    canonical_input = dict(snapshot)
    canonical_input["max_active_lanes"] = slots
    canonical_input.pop("stabilization_issue", None)
    plan = scheduler.build_plan(canonical_input)

    selected = list(plan.get("selected") or [])
    if any("number" not in item for item in selected):
        raise RuntimeError("canonical planner returned malformed selected item")

    workers = []
    for ordinal, item in enumerate(selected[:slots], start=1):
        workers.append(
            {
                "slot": ordinal,
                "issue_number": int(item["number"]),
                "lane_id": str(item.get("lane_id") or "UNASSIGNED"),
                "priority": int(item.get("priority", 4)),
                "selection_reason": str(item.get("selection_reason") or "priority"),
                "repair": bool(item.get("repair")),
            }
        )

    return {
        "schema": "oc.swarm-plan.v1",
        "requested_worker_slots": int(worker_slots),
        "effective_worker_slots": slots,
        "active_worker_count": int(plan.get("active_lane_count") or 0),
        "launch_count": len(workers),
        "workers": workers,
        "matrix": {"include": workers},
        "selected_numbers": [w["issue_number"] for w in workers],
        "suppressed": list(plan.get("suppressed") or []),
        "eligible_count": int(plan.get("eligible_count") or 0),
        "generated_at": plan.get("generated_at"),
        "safety": {
            "merge_to_main": False,
            "production_deploy": False,
            "provider_calls_in_planner": False,
            "owner_gates_preserved": True,
            "bounded": True,
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
