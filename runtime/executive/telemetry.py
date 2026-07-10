from __future__ import annotations

from typing import Any

from app.routers.mission_control import (
    completeness_rows,
    harvester_rows,
    metric_snapshot,
    mission_control_governance,
    mission_control_recommendations,
    runtime_telemetry,
)

from runtime.executive.dependencies import dependency_graph
from runtime.executive.executive_state import ExecutiveSubsystem, utc_now

SYSTEM_DEFINITIONS: dict[str, dict[str, Any]] = {
    "mission_control": {"name": "Mission Control", "category": "Executive", "source": "mission_control"},
    "atlas": {"name": "Atlas", "category": "Science", "source": "occurrences"},
    "species_explorer": {"name": "Species Explorer", "category": "Science", "source": "taxonomy"},
    "knowledge_graph": {"name": "Knowledge Graph", "category": "Relationships", "source": "relationships"},
    "literature": {"name": "Literature", "category": "Science", "source": "literature"},
    "pollinators": {"name": "Pollinators", "category": "Ecology", "source": "relationships"},
    "mycorrhiza": {"name": "Mycorrhiza", "category": "Ecology", "source": "mycorrhiza"},
    "vision_lab": {"name": "Vision Lab", "category": "Media", "source": "images"},
    "grant_office": {"name": "Grant Office", "category": "Funding", "source": "build051_intelligence"},
    "partnership_generator": {"name": "Partnership Generator", "category": "Partnerships", "source": "build051_packets"},
    "harvesters": {"name": "Harvesters", "category": "Pipelines", "source": "harvester_registry"},
    "runtime_jobs": {"name": "Runtime Jobs", "category": "Runtime", "source": "runtime_jobs"},
    "governance": {"name": "Governance", "category": "Governance", "source": "governance"},
    "build_history": {"name": "Build History", "category": "Delivery", "source": "repositories"},
    "recommendations": {"name": "Recommendations", "category": "Executive", "source": "recommendation_engine"},
    "health": {"name": "Health", "category": "Executive", "source": "health_rollup"},
    "completeness": {"name": "Completeness", "category": "Executive", "source": "completeness_rollup"},
    "integrations": {"name": "Integrations", "category": "Connectors", "source": "connector_registry"},
}


def _status_from_completion(completion: int, blockers: list[str]) -> str:
    if blockers and completion < 35:
        return "blocked"
    if completion >= 75:
        return "healthy"
    if completion >= 40:
        return "warning"
    return "planned"


def _confidence(completion: int, blockers: list[str], source: str) -> float:
    base = 0.35 + min(max(completion, 0), 100) / 200
    if source == "not connected":
        base -= 0.2
    if blockers:
        base -= min(0.25, len(blockers) * 0.05)
    return round(max(0.1, min(0.95, base)), 2)


def _from_completeness_rows() -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for row in completeness_rows():
        mapped[str(row.get("id"))] = row
    return mapped


def collect_subsystems() -> list[ExecutiveSubsystem]:
    graph = dependency_graph()
    metrics = metric_snapshot()
    metric_rows = metrics.get("metrics") or {}
    completeness = _from_completeness_rows()
    harvesters = harvester_rows()
    runtime = runtime_telemetry()
    generated_at = metrics.get("generated_at") or utc_now()

    subsystems: list[ExecutiveSubsystem] = []
    for system_id, definition in SYSTEM_DEFINITIONS.items():
        row = completeness.get(system_id)
        source_key = definition["source"]
        metric = metric_rows.get(source_key, {}) if isinstance(metric_rows, dict) else {}
        blockers = list(row.get("blockers", []) if row else [])
        source = str(row.get("telemetry_source") if row else metric.get("table") or definition["source"])
        completion = int(row.get("completion") or row.get("completeness") or 0) if row else 0

        if system_id == "mission_control":
            completion = 80 if metrics.get("database_connected") else 45
            source = "mission_control_runtime"
        elif system_id == "harvesters":
            connected = sum(1 for item in harvesters if item.get("enabled"))
            completion = max(25, min(85, 30 + connected * 5))
            blockers = sorted({error for item in harvesters for error in item.get("errors", [])})
            source = "harvester_registry"
        elif system_id == "runtime_jobs":
            completion = int(runtime.get("completion") or 25)
            blockers = [str(runtime.get("blocker_text"))] if runtime.get("blocker_text") else []
            source = str(runtime.get("telemetry_source") or "runtime")
        elif system_id == "governance":
            governance = mission_control_governance()
            completion = 70 if governance.get("policies") else 35
            blockers = []
            source = "constitutional_governance"
        elif system_id == "build_history":
            completion = 55
            blockers = ["Live GitHub deployment/build connector is not yet attached."]
            source = "repository_registry"
        elif system_id in {"grant_office", "partnership_generator", "recommendations", "health", "completeness", "integrations"}:
            completion = {
                "grant_office": 48,
                "partnership_generator": 48,
                "recommendations": 65,
                "health": 65,
                "completeness": 60,
                "integrations": 42,
            }[system_id]
            blockers = [] if system_id in {"recommendations", "health", "completeness"} else ["Needs deeper source-specific persistence telemetry."]

        if not row and source_key in metric_rows and not metric.get("available"):
            blockers.append(f"No connected telemetry table for {definition['name']}.")

        status = _status_from_completion(completion, blockers)
        confidence = _confidence(completion, blockers, source)
        subsystems.append(
            ExecutiveSubsystem(
                id=system_id,
                name=definition["name"],
                category=definition["category"],
                status=status,
                health=status,
                completion=max(0, min(100, completion)),
                dependencies=graph.get(system_id, []),
                blockers=blockers,
                owner_required=bool(blockers) or status in {"blocked", "warning", "planned"},
                confidence=confidence,
                last_updated=generated_at,
                source=source,
                summary=f"{definition['name']} is {status} at {completion}% completion from {source}.",
                metrics={"source_metric": metric, "database_connected": bool(metrics.get("database_connected"))},
            )
        )
    return subsystems


def source_recommendations() -> list[dict[str, Any]]:
    return list(mission_control_recommendations().get("recommendations") or [])

