from __future__ import annotations

from copy import deepcopy
from typing import Any

from runtime.executive.dependencies import dependency_graph, reverse_dependencies
from runtime.executive.executive_state import utc_now
from runtime.executive.reasoning import attach_reasoning
from runtime.executive.recommendations import generate_recommendations
from runtime.executive.scorer import ordered_priorities
from runtime.executive.summarizer import executive_briefing, executive_summary
from runtime.executive.telemetry import collect_subsystems

_PREVIOUS_STATE: dict[str, Any] | None = None


def detect_changes(current: dict[str, Any], previous: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not previous:
        return [{"type": "baseline", "summary": "Initial executive state baseline captured.", "severity": "info"}]
    changes: list[dict[str, Any]] = []
    previous_by_id = {item["id"]: item for item in previous.get("subsystems", [])}
    current_by_id = {item["id"]: item for item in current.get("subsystems", [])}
    for system_id, subsystem in current_by_id.items():
        old = previous_by_id.get(system_id)
        if not old:
            changes.append({"type": "new_system", "system_id": system_id, "summary": f"{subsystem['name']} entered executive state.", "severity": "info"})
            continue
        if subsystem["completion"] > old.get("completion", 0):
            changes.append({"type": "health_improvement", "system_id": system_id, "summary": f"{subsystem['name']} completion improved.", "severity": "info"})
        if subsystem["completion"] < old.get("completion", 0) or subsystem["status"] in {"blocked", "warning"} and old.get("status") == "healthy":
            changes.append({"type": "regression", "system_id": system_id, "summary": f"{subsystem['name']} regressed or needs attention.", "severity": "warning"})
        new_blockers = set(subsystem.get("blockers", [])) - set(old.get("blockers", []))
        for blocker in sorted(new_blockers):
            changes.append({"type": "new_blocker", "system_id": system_id, "summary": blocker, "severity": "warning"})
    for system_id in sorted(set(previous_by_id) - set(current_by_id)):
        changes.append({"type": "removed_system", "system_id": system_id, "summary": f"{system_id} disappeared from executive state.", "severity": "warning"})
    return changes


def build_executive_state(update_cache: bool = True) -> dict[str, Any]:
    global _PREVIOUS_STATE
    graph = dependency_graph()
    reverse = reverse_dependencies(graph)
    subsystems = [item.as_dict() for item in collect_subsystems()]
    priorities = attach_reasoning(ordered_priorities(subsystems, reverse))
    current = {
        "build": "BUILD-052",
        "generated_at": utc_now(),
        "subsystems": subsystems,
        "dependencies": {"graph": graph, "reverse": reverse},
        "priorities": priorities,
        "recommendations": generate_recommendations(priorities, subsystems),
    }
    current["changes"] = detect_changes(current, _PREVIOUS_STATE)
    current["summary"] = executive_summary(current)
    current["briefing"] = executive_briefing(current)
    if update_cache:
        _PREVIOUS_STATE = deepcopy(current)
    return current


def reset_previous_state() -> None:
    global _PREVIOUS_STATE
    _PREVIOUS_STATE = None

