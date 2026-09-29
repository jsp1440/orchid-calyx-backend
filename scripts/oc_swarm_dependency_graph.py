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
    r"^OC-SWARM-DEPENDS-ON:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE
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


def _validate_dependencies_declaration(issue: dict) -> str | None:
    """Validate the OC-SWARM-DEPENDS-ON declaration for an issue.

    Returns:
        None if the declaration is valid (or absent), or a machine-readable
        error string if the declaration is malformed.
    """
    body = str(issue.get("body") or "")
    matches = list(DEPENDS_MARKER.finditer(body))

    # No declaration at all is valid.
    if not matches:
        return None

    # Multiple declarations are invalid (repeated lines must fail).
    if len(matches) > 1:
        return "malformed-declaration-repeated"

    match = matches[0]
    decl_text = match.group(1)

    # Empty or whitespace-only declaration is invalid.
    if not decl_text or not decl_text.strip():
        return "malformed-declaration-empty"

    # Extract all issue references.
    raw_refs = ISSUE_REF.findall(decl_text)
    if not raw_refs:
        # Non-reference: declaration line has no valid #NNN pattern.
        return "malformed-declaration-non-reference"

    # Convert to integers and validate: reject #0 and any invalid.
    has_invalid = False

    for ref_str in raw_refs:
        num = int(ref_str)
        if num == 0:
            has_invalid = True
            break

    if has_invalid:
        return "malformed-declaration-zero-reference"

    # Check for mixed valid/invalid by looking for non-#NNN content after stripping references.
    # If the declaration has content that is not a valid reference or comma/whitespace, reject it.
    stripped = decl_text
    for ref_str in raw_refs:
        stripped = stripped.replace(f"#{ref_str}", "", 1)
    # What remains should be only commas and whitespace.
    if stripped and stripped.strip() and not all(c in ", \t\n\r" for c in stripped):
        return "malformed-declaration-mixed-invalid"

    return None


def dependencies(issue: dict) -> list[int]:
    """Return the explicit dependency issue numbers for one issue."""
    body = str(issue.get("body") or "")
    match = DEPENDS_MARKER.search(body)
    if not match:
        return []
    refs = sorted({int(value) for value in ISSUE_REF.findall(match.group(1))})
    return refs


def _is_satisfied(issue: dict | None) -> bool:
    if issue is None:
        return False
    state = str(issue.get("state") or "OPEN").upper()
    return state == "CLOSED" or DONE_LABEL in _labels(issue)


def build_dependency_graph(issues: Iterable[dict]) -> dict[str, Any]:
    rows = [issue for issue in issues if issue.get("number") is not None]
    index = {int(issue["number"]): issue for issue in rows}
    edges: dict[int, list[int]] = {}
    errors: dict[int, str] = {}

    for number, issue in index.items():
        error = _validate_dependencies_declaration(issue)
        if error is not None:
            errors[number] = error
            edges[number] = []
        else:
            edges[number] = dependencies(issue)

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
        # If there's a validation error for this issue, mark it as blocked.
        if number in errors:
            status[number] = {
                "issue_number": number,
                "dependencies": [],
                "missing": [],
                "unsatisfied": [],
                "cycle": False,
                "ready": False,
                "error": errors[number],
            }
        else:
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
