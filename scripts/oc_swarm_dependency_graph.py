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


class MalformedDependencyDeclaration(Exception):
    """Raised when a dependency declaration is syntactically invalid."""
    pass


def _labels(issue: dict) -> set[str]:
    result: set[str] = set()
    for label in issue.get("labels") or []:
        if isinstance(label, str):
            result.add(label)
        elif isinstance(label, dict) and label.get("name"):
            result.add(str(label["name"]))
    return result


def _validate_dependency_declaration(declaration_text: str) -> tuple[list[int], str | None]:
    """Parse and validate a dependency declaration.
    
    Args:
        declaration_text: The text after 'OC-SWARM-DEPENDS-ON:'
        
    Returns:
        (issue_numbers, error_reason) where error_reason is None if valid,
        or a machine-readable error string if malformed.
    """
    # Strip whitespace
    text = declaration_text.strip()
    
    # Empty declaration is malformed
    if not text:
        return [], "dependency-declaration-empty"
    
    # Find all issue references
    refs = [int(value) for value in ISSUE_REF.findall(text)]
    
    # If no issue references found, it's malformed
    if not refs:
        return [], "dependency-declaration-no-references"
    
    # Check if there's any non-reference content that could indicate malformation
    # Remove all valid issue references from the text
    cleaned = re.sub(r"#\d+", "", text)
    # Remove common separators and whitespace
    cleaned = re.sub(r"[\s,;]+", "", cleaned)
    
    # If there's leftover content, it's mixed valid/invalid
    if cleaned:
        return [], "dependency-declaration-mixed-content"
    
    # Check for zero or negative numbers (shouldn't happen with \d+ but be safe)
    if any(ref <= 0 for ref in refs):
        return [], "dependency-declaration-invalid-number"
    
    # Return sorted unique references
    return sorted(set(refs)), None


def dependencies(issue: dict) -> list[int]:
    """Return the explicit dependency issue numbers for one issue."""
    body = str(issue.get("body") or "")
    match = DEPENDS_MARKER.search(body)
    if not match:
        return []
    
    # Use the validation function
    issue_numbers, error = _validate_dependency_declaration(match.group(1))
    
    # Store malformation status in the issue for later use in build_dependency_graph
    if error:
        issue["_dependency_malformed"] = error
    
    return issue_numbers


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
        # Check if the issue has a malformed dependency declaration
        malformed = index[number].get("_dependency_malformed")
        
        missing = [dep for dep in deps if dep not in index]
        unsatisfied = [dep for dep in deps if dep in index and not _is_satisfied(index[dep])]
        cycle = number in cycle_nodes
        
        # Mark as not ready if there's a malformed declaration
        ready = not missing and not unsatisfied and not cycle and not malformed
        
        status_entry: dict[str, Any] = {
            "issue_number": number,
            "dependencies": deps,
            "missing": missing,
            "unsatisfied": unsatisfied,
            "cycle": cycle,
            "ready": ready,
        }
        
        # Add malformed reason if present
        if malformed:
            status_entry["malformed"] = malformed
        
        status[number] = status_entry

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
        
        # Determine the blocking reason
        if row.get("malformed"):
            reason = row["malformed"]
        elif row.get("cycle"):
            reason = "dependency-cycle"
        else:
            reason = "dependency-blocked"
        
        blocked_entry: dict[str, Any] = {
            "issue_number": number,
            "reason": reason,
            "dependencies": list(row.get("dependencies") or []),
            "missing": list(row.get("missing") or []),
            "unsatisfied": list(row.get("unsatisfied") or []),
        }
        
        blocked.append(blocked_entry)
    return ready, blocked
