#!/usr/bin/env python3
"""Deterministic dependency graph for Orchid Continuum Swarm v4.

Dependencies are explicit and durable. Issues may declare:

    OC-SWARM-DEPENDS-ON: #1201, #1202

A dependency is satisfied only when the referenced issue is closed or carries
``oc-done``. Missing referenced issues fail closed. Cycles are detected and all
members of a cycle remain blocked. This module is pure and provider-free.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

DEPENDS_MARKER = re.compile(
    r"^OC-SWARM-DEPENDS-ON:\s*(.*)$", re.IGNORECASE | re.MULTILINE
)
ISSUE_REF = re.compile(r"#(\d+)")
DONE_LABEL = "oc-done"


def _labels(issue: dict) -> set[str]:
    result: set[str] = set()
    for label in issue.get("labels") or []:
        if isinstance(label, str):
            result.add(label)
        elif isinstance(label, dict) and label.get("name"):
            result.add(str(label["name"]))
    return result


def dependencies(issue: dict) -> list[int]:
    """Return the explicit dependency issue numbers for one issue."""
    body = str(issue.get("body") or "")
    match = DEPENDS_MARKER.search(body)
    if not match:
        return []
    current = issue.get("number")
    refs = sorted({int(value) for value in ISSUE_REF.findall(match.group(1))})
    if current is not None:
        refs = [number for number in refs if number != int(current)]
    return refs


def _is_satisfied(issue: dict | None) -> bool:
    if issue is None:
        return False
    state = str(issue.get("state") or "OPEN").upper()
    return state == "CLOSED" or DONE_LABEL in _labels(issue)


def build_dependency_graph(issues: Iterable[dict]) -> dict[str, Any]:
    rows = [issue for issue in issues if issue.get("number") is not None]
    index = {int(issue["number"]): issue for issue in rows}
    edges = {number: dependencies(issue) for number, issue in index.items()}

    # DFS cycle detection over known nodes only. Missing nodes are handled as
    # unsatisfied dependencies rather than graph vertices.
    visiting: set[int] = set()
    visited: set[int] = set()
    cycle_nodes: set[int] = set()
    stack: list[int] = []

    def visit(node: int) -> None:
        if node in visited:
            return
        if node in visiting:
            try:
                start = stack.index(node)
            except ValueError:
                start = 0
            cycle_nodes.update(stack[start:])
            cycle_nodes.add(node)
            return
        visiting.add(node)
        stack.append(node)
        for dep in edges.get(node, []):
            if dep in index:
                visit(dep)
        stack.pop()
        visiting.discard(node)
        visited.add(node)

    for node in sorted(index):
        visit(node)

    status: dict[int, dict[str, Any]] = {}
    for number, deps in edges.items():
        missing = [dep for dep in deps if dep not in index]
        unsatisfied = [dep for dep in deps if dep in index and not _is_satisfied(index[dep])]
        cycle = number in cycle_nodes
        ready = not missing and not unsatisfied and not cycle
        status[number] = {
            "issue_number": number,
            "dependencies": deps,
            "missing": missing,
            "unsatisfied": unsatisfied,
            "cycle": cycle,
            "ready": ready,
        }

    return {
        "schema": "oc.swarm-dependency-graph.v1",
        "status": status,
        "cycle_nodes": sorted(cycle_nodes),
        "edge_count": sum(len(values) for values in edges.values()),
    }


def filter_ready_candidates(
    ranked: Iterable[dict], graph: dict[str, Any]
) -> tuple[list[dict], list[dict]]:
    """Partition canonical ranked candidates by dependency readiness."""
    ready: list[dict] = []
    blocked: list[dict] = []
    status = graph.get("status") or {}
    for item in ranked:
        if item.get("number") is None:
            continue
        number = int(item["number"])
        row = status.get(number) or status.get(str(number))
        if row is None:
            blocked.append({"issue_number": number, "reason": "dependency-status-missing"})
            continue
        if row.get("ready"):
            ready.append(item)
            continue
        reason = "dependency-cycle" if row.get("cycle") else "dependency-blocked"
        blocked.append(
            {
                "issue_number": number,
                "reason": reason,
                "dependencies": list(row.get("dependencies") or []),
                "missing": list(row.get("missing") or []),
                "unsatisfied": list(row.get("unsatisfied") or []),
            }
        )
    return ready, blocked
