#!/usr/bin/env python3
"""Bounded parallel execution planner for the Orchid Continuum software factory.

Swarm v4 composes three independent safety layers:
1. canonical queue/priority/durable-PR eligibility;
2. explicit dependency readiness;
3. semantic read/write resource locking.

Only dependency-ready, resource-compatible work is admitted. The planner is
pure: it does not call model providers, mutate GitHub, merge, deploy, spend
money, or cross owner gates.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from typing import Any


def _load_routing():
    """Import the capability router without requiring the app package on sys.path."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    if root not in sys.path:
        sys.path.insert(0, root)
    from app.provider_reservoir import routing

    return routing


DEFAULT_WORKER_SLOTS = 8
MAX_WORKER_SLOTS = 12
# Routing is capability-based; see app/provider_reservoir/routing.py. This module
# keeps a local import path so the controller runs from a bare checkout.
_ROUTING = _load_routing()
PROVIDER_FREE_MARKER = _ROUTING.PROVIDER_FREE_MARKER


def _load_sibling(module_name: str, filename: str):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, filename)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"required swarm module unavailable: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_provider_free(issue: dict) -> bool:
    """True when the issue has deterministic work that can run now.

    Routing is by declared capability, not by difficulty and not by one
    hard-coded task name. The predicate this replaced matched only the literal
    ``OC-SWARM-PROVIDER-FREE: reconcile``, so every other provider-free task fell
    through to the paid lane — which is how #1502 reached `claude-opus-5` with
    `reason=deep-complexity-signal` while its own acceptance criteria required a
    fixture that "must run without external AI credentials".

    A task carrying optional provider enrichment is still provider-free: the
    enrichment parks by itself and the deterministic work proceeds.
    """
    return _ROUTING.is_provider_free(issue)


def route_task(issue: dict):
    """Full routing decision for an issue, including what parks and why."""
    return _ROUTING.route_task(issue)


def is_lane_executable(issue: dict) -> bool:
    """True when the deterministic worker job has an executor for this task.

    Admission to the provider-free lane asks this, not ``is_provider_free``.
    The two were conflated, and #1502 is what that costs: it declares eight
    deterministic capabilities, so it is genuinely provider-free, and it was
    handed to a worker whose only mode reconciles GitHub state. The worker
    refused a marker the issue had no reason to carry and the issue was marked
    ``oc-blocked`` — a label that removes work from the portfolio for good.

    A capability list says what to build. It does not name anyone who can
    build it.
    """
    return _ROUTING.is_lane_executable(issue)


def lane_refusal(issue: dict) -> dict:
    """A durable record of deterministic work this lane cannot staff.

    Kept distinct from a blocker on purpose. Nothing is stopping this task; the
    lane simply has no executor for it, which is a gap in the factory rather
    than a gap in the work, and it belongs in Improvement Discovery as
    ``missing_capability`` rather than in the blocked pile.
    """
    routing = route_task(issue)
    return {
        "schema": "oc.lane-refusal.v1",
        "issue_number": routing.issue_number,
        "provider_free": routing.provider_free,
        "lane_executable": False,
        "reason": routing.unexecutable_reason,
        "declared_deterministic_capabilities": list(routing.deterministic_capabilities),
        "parked_capabilities": routing.parked_capabilities,
        "blocked": False,
    }


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


def _strip_queue_label(issue: dict) -> dict:
    """Return the issue without ``oc-queued``, leaving every other field alone.

    Removing the queue label keeps the issue out of candidacy for this pass
    without touching its durable state: dependency edges, resource claims and
    priority all still read correctly for everything else in the plan.
    """
    stripped = dict(issue)
    labels = []
    for label in issue.get("labels") or []:
        name = label if isinstance(label, str) else label.get("name")
        if name != "oc-queued":
            labels.append(label)
    stripped["labels"] = labels
    return stripped


def unstaffed_numbers(snapshot: dict) -> list[int]:
    """Open queued issues that need no provider and that no executor implements.

    These are the ones that belong to neither lane. Leaving them in candidacy
    is not harmless: they sort by priority like anything else, and a resource
    claim they can never use is still exclusive. A P0 task nothing can run will
    take the lane and the ``control-plane`` lock and hold both against a P4 task
    that was ready to execute — which is the work-conservation rule failing, not
    merely a label being wrong.
    """
    numbers: list[int] = []
    for issue in snapshot.get("issues") or []:
        if str(issue.get("state") or "").upper() != "OPEN":
            continue
        names = {
            label if isinstance(label, str) else label.get("name")
            for label in issue.get("labels") or []
        }
        if "oc-queued" not in names:
            continue
        if is_lane_executable(issue):
            continue
        if not is_provider_free(issue):
            # Genuinely needs a provider: the governed completion lane owns it.
            continue
        if issue.get("number") is not None:
            numbers.append(int(issue["number"]))
    return numbers


def _provider_free_snapshot(snapshot: dict) -> dict:
    """Hide entries this lane cannot execute, without losing dependency state.

    This used to match ``PROVIDER_FREE_MARKER`` directly while the plan builder
    below asked the capability router — two notions of "provider-free" in one
    file, disagreeing about the same issue. The router is the single answer now,
    and the question it is asked here is executability, not provider-freedom.
    """
    filtered = dict(snapshot)
    issues = []
    for original in snapshot.get("issues") or []:
        issue = dict(original)
        if (
            str(issue.get("state") or "").upper() == "OPEN"
            and not is_lane_executable(issue)
        ):
            labels = []
            for label in issue.get("labels") or []:
                name = label if isinstance(label, str) else label.get("name")
                if name != "oc-queued":
                    labels.append(label)
            issue["labels"] = labels
        issues.append(issue)
    filtered["issues"] = issues
    return filtered


def build_swarm_plan(
    snapshot: dict,
    *,
    worker_slots: int = DEFAULT_WORKER_SLOTS,
    provider_free_only: bool = False,
) -> dict:
    """Return a dependency- and resource-aware worker matrix."""
    slots = _bounded_slots(worker_slots)
    scheduler = _load_sibling("oc_portfolio_scheduler", "oc_portfolio_scheduler.py")
    locks = _load_sibling("oc_swarm_resource_locks", "oc_swarm_resource_locks.py")
    deps = _load_sibling("oc_swarm_dependency_graph", "oc_swarm_dependency_graph.py")

    planning_snapshot = _provider_free_snapshot(snapshot) if provider_free_only else snapshot

    # Work nothing can execute is withdrawn from candidacy before selection, so
    # it cannot take a lane or hold a resource lock away from work that can run.
    unstaffed = set(unstaffed_numbers(planning_snapshot))
    if unstaffed:
        planning_snapshot = dict(planning_snapshot)
        planning_snapshot["issues"] = [
            _strip_queue_label(issue)
            if int(issue.get("number") or 0) in unstaffed
            else issue
            for issue in planning_snapshot.get("issues") or []
        ]

    canonical_input = dict(planning_snapshot)
    canonical_input["max_active_lanes"] = slots
    canonical_input.pop("stabilization_issue", None)
    plan = scheduler.build_plan(canonical_input)

    issues = _issue_index(planning_snapshot)
    graph = deps.build_dependency_graph(planning_snapshot.get("issues") or [])
    ready_ranked, dependency_suppressed = deps.filter_ready_candidates(
        plan.get("ranking") or [], graph
    )

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
    for ranked in ready_ranked:
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
        issue_number = int(item["issue_number"])
        dep_status = (graph.get("status") or {}).get(issue_number) or {}
        workers.append(
            {
                "slot": ordinal,
                "issue_number": issue_number,
                "lane_id": str(item.get("lane_id") or "UNASSIGNED"),
                "priority": int(item.get("priority", 4)),
                "selection_reason": str(item.get("selection_reason") or "dependency-resource-priority"),
                "repair": bool(item.get("repair")),
                "reads": list(item.get("reads") or []),
                "writes": list(item.get("writes") or []),
                "dependencies": list(dep_status.get("dependencies") or []),
                "provider_free": is_provider_free(issues[issue_number]),
                "lane_executable": is_lane_executable(issues[issue_number]),
            }
        )

    # One plan, two execution lanes, and a third outcome that is neither.
    #
    # The deterministic job takes what it has an executor for. The governed
    # completion lane takes what genuinely needs a provider. Work that needs no
    # provider but that no executor implements goes to neither: sending it to
    # the deterministic worker gets it marked blocked for a missing marker, and
    # sending it to the paid lane is the misrouting the router was repaired to
    # stop. It is recorded instead, so it stays visible as a missing capability.
    provider_free_workers = [worker for worker in workers if worker["lane_executable"]]
    provider_workers = [worker for worker in workers if not worker["lane_executable"]]
    # Recorded from the withdrawn set rather than from the selected workers:
    # they are withdrawn precisely so they never become workers, and a refusal
    # nobody writes down is how the 01:04 diagnosis got lost the first time.
    lane_refusals = [
        lane_refusal(issues[number]) for number in sorted(unstaffed) if number in issues
    ]

    # A later wave can make progress when queued work exists but is blocked only
    # by active workers or unresolved dependencies. The workflow uses this as an
    # observability/refill hint; it never bypasses the dependency graph.
    # Every dependency-ready candidate not selected remains live work for a
    # later wave. ``select_with_resource_locks`` stops once capacity is full,
    # so its suppression list alone cannot account for compatible overflow.
    waiting_count = len(dependency_suppressed) + max(0, len(candidates) - len(selected))
    refill_recommended = bool(active_count or workers) and waiting_count > 0

    return {
        "schema": "oc.swarm-plan.v4",
        "requested_worker_slots": int(worker_slots),
        "effective_worker_slots": slots,
        "active_worker_count": active_count,
        "available_capacity": capacity,
        "launch_count": len(workers),
        "workers": workers,
        "matrix": {"include": workers},
        "provider_free_workers": provider_free_workers,
        "provider_workers": provider_workers,
        "provider_free_matrix": {"include": provider_free_workers},
        "provider_matrix": {"include": provider_workers},
        "provider_free_launch_count": len(provider_free_workers),
        "provider_launch_count": len(provider_workers),
        "unstaffed_numbers": sorted(unstaffed),
        "lane_refusals": lane_refusals,
        "unstaffed_count": len(unstaffed),
        "selected_numbers": [worker["issue_number"] for worker in workers],
        "dependency_graph": {
            "edge_count": int(graph.get("edge_count") or 0),
            "cycle_nodes": list(graph.get("cycle_nodes") or []),
        },
        "dependency_suppressed": dependency_suppressed,
        "active_resource_locks": active_locks,
        "resource_lock_suppressed": lock_suppressed,
        "canonical_suppressed": list(plan.get("suppressed") or []),
        "eligible_count": int(plan.get("eligible_count") or 0),
        "waiting_count": waiting_count,
        "refill_recommended": refill_recommended,
        "generated_at": plan.get("generated_at"),
        "safety": {
            "merge_to_main": False,
            "production_deploy": False,
            "provider_calls_in_planner": False,
            "owner_gates_preserved": True,
            "bounded": True,
            "dependency_graph": True,
            "dependency_cycles_fail_closed": True,
            "missing_dependencies_fail_closed": True,
            "resource_locking": True,
            "read_read_parallelism": True,
            "write_conflicts_fail_closed": True,
            "provider_free_only": provider_free_only,
            "provider_free_lane_split": True,
        },
    }


def _write_github_output(path: str, plan: dict) -> None:
    matrix = json.dumps(plan["matrix"], separators=(",", ":"))
    summary = json.dumps(plan, separators=(",", ":"))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"matrix={matrix}\n")
        handle.write(f"launch_count={plan['launch_count']}\n")
        handle.write(
            "provider_free_matrix="
            + json.dumps(plan["provider_free_matrix"], separators=(",", ":"))
            + "\n"
        )
        handle.write(
            "provider_matrix="
            + json.dumps(plan["provider_matrix"], separators=(",", ":"))
            + "\n"
        )
        handle.write(f"provider_free_launch_count={plan['provider_free_launch_count']}\n")
        handle.write(f"provider_launch_count={plan['provider_launch_count']}\n")
        handle.write(f"selected_numbers={json.dumps(plan['selected_numbers'], separators=(',', ':'))}\n")
        handle.write(f"refill_recommended={str(plan['refill_recommended']).lower()}\n")
        handle.write(f"summary={summary}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="JSON snapshot path, or - for stdin")
    parser.add_argument("--worker-slots", type=int, default=DEFAULT_WORKER_SLOTS)
    parser.add_argument("--provider-free-only", action="store_true")
    parser.add_argument("--github-output", help="optional GITHUB_OUTPUT path")
    args = parser.parse_args(argv)

    if args.input == "-":
        snapshot = json.load(sys.stdin)
    else:
        with open(args.input, encoding="utf-8") as handle:
            snapshot = json.load(handle)

    plan = build_swarm_plan(
        snapshot,
        worker_slots=args.worker_slots,
        provider_free_only=args.provider_free_only,
    )
    if args.github_output:
        _write_github_output(args.github_output, plan)
    json.dump(plan, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
