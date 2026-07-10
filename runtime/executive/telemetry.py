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

COMPLETION_WEIGHTS = {
    "functional_backend": 0.30,
    "data_coverage": 0.20,
    "scientific_validation": 0.15,
    "integration_readiness": 0.15,
    "automation_readiness": 0.10,
    "operational_reliability": 0.10,
}


def completion_model() -> dict[str, Any]:
    return {
        "weights": COMPLETION_WEIGHTS,
        "formula": "functional_backend*0.30 + data_coverage*0.20 + scientific_validation*0.15 + integration_readiness*0.15 + automation_readiness*0.10 + operational_reliability*0.10",
        "inputs": [
            "reachable backend route or runtime service",
            "reachable source tables and source record counts",
            "relationship/evidence coverage",
            "configured integrations and credentials",
            "safe owner-authorized action path or read-only automation state",
            "recent jobs, failures, blockers, and telemetry freshness",
        ],
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


def _metric_count(metric: dict[str, Any]) -> int:
    return int(metric.get("count") or 0)


def _coverage_from_metric(metric: dict[str, Any], target: int = 1000) -> int:
    if not metric.get("available"):
        return 0
    count = _metric_count(metric)
    if count <= 0:
        return 20
    return max(35, min(100, int((count / target) * 100)))


def _freshness(metric: dict[str, Any], generated_at: str) -> str:
    if not metric.get("available"):
        return "source table unavailable"
    return f"verified at {generated_at}"


def _score_completion(
    *,
    functional_backend: int,
    data_coverage: int,
    scientific_validation: int,
    integration_readiness: int,
    automation_readiness: int,
    operational_reliability: int,
) -> int:
    score = (
        functional_backend * COMPLETION_WEIGHTS["functional_backend"]
        + data_coverage * COMPLETION_WEIGHTS["data_coverage"]
        + scientific_validation * COMPLETION_WEIGHTS["scientific_validation"]
        + integration_readiness * COMPLETION_WEIGHTS["integration_readiness"]
        + automation_readiness * COMPLETION_WEIGHTS["automation_readiness"]
        + operational_reliability * COMPLETION_WEIGHTS["operational_reliability"]
    )
    return max(0, min(100, int(round(score))))


def _source_counts(metric: dict[str, Any]) -> dict[str, int]:
    table = metric.get("table")
    if not table:
        return {}
    return {str(table): _metric_count(metric)}


def _activation_status(subsystem: ExecutiveSubsystem) -> str:
    if subsystem.status == "healthy" and subsystem.completion >= 75:
        return "Fully Operational"
    if subsystem.source == "not connected" or subsystem.telemetry_freshness == "source table unavailable":
        return "Blocked by Missing Database Object"
    if subsystem.blockers:
        if any("credential" in blocker.lower() or "oauth" in blocker.lower() for blocker in subsystem.blockers):
            return "Blocked by Missing Credential"
        if any("external" in blocker.lower() or "connector" in blocker.lower() for blocker in subsystem.blockers):
            return "Blocked by Missing External Service"
    if subsystem.completion > 0:
        return "Operational with Limited Coverage"
    return "Not Implemented"


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
        data_coverage = _coverage_from_metric(metric)
        evidence_quality = 70 if metric.get("available") and _metric_count(metric) > 0 else 25 if metric.get("available") else 0
        integration_readiness = 65 if metrics.get("database_connected") else 15
        automation_readiness = 40 if system_id in {"harvesters", "runtime_jobs"} else 55 if system_id in {"mission_control", "governance", "recommendations", "health", "completeness"} else 30
        operational_reliability = 70 if not blockers and metrics.get("database_connected") else 35
        functional_backend = 80 if row or system_id in {"mission_control", "governance", "recommendations", "health", "completeness"} else 45
        scientific_validation = evidence_quality if definition["category"] in {"Science", "Ecology", "Media", "Relationships"} else 45
        active_jobs = 0
        failures: list[str] = []
        recommended_action = str(row.get("recommended_next_action") if row else "Connect telemetry source and verify owner action path.")
        telemetry_freshness = _freshness(metric, str(generated_at))

        if system_id == "mission_control":
            functional_backend = 90
            data_coverage = 80 if metrics.get("database_connected") else 35
            evidence_quality = 80 if metrics.get("database_connected") else 35
            integration_readiness = 75 if metrics.get("database_connected") else 25
            automation_readiness = 70
            operational_reliability = 80 if metrics.get("database_connected") else 40
            source = "mission_control_runtime"
            telemetry_freshness = str(generated_at)
            recommended_action = "Use executive state as the Mission Control source of truth and deploy backend/frontend together."
        elif system_id == "harvesters":
            connected = sum(1 for item in harvesters if item.get("enabled"))
            active_jobs = sum(1 for item in harvesters if item.get("state") == "running")
            blockers = sorted({error for item in harvesters for error in item.get("errors", [])})
            failures = blockers
            functional_backend = 85
            data_coverage = max(20, min(100, connected * 9))
            evidence_quality = 65 if connected else 30
            integration_readiness = 70 if connected else 40
            automation_readiness = 75
            operational_reliability = 80 if not failures else 35
            source = "harvester_registry"
            telemetry_freshness = "latest job heartbeat" if connected else "no job heartbeat found"
            recommended_action = "Run one owner-authorized low-risk harvester action after deployment smoke tests."
        elif system_id == "runtime_jobs":
            blockers = [str(runtime.get("blocker_text"))] if runtime.get("blocker_text") else []
            runtime_metric = runtime.get("metrics", {}).get("runtime_jobs", {}) if isinstance(runtime.get("metrics"), dict) else {}
            data_coverage = _coverage_from_metric(runtime_metric, 10)
            evidence_quality = 70 if runtime_metric.get("available") else 10
            functional_backend = 80
            integration_readiness = 55 if runtime.get("database_connected") else 15
            automation_readiness = 70 if runtime_metric.get("available") else 25
            operational_reliability = 75 if not blockers else 35
            source = str(runtime.get("telemetry_source") or "runtime")
            telemetry_freshness = str(runtime.get("last_update") or generated_at)
            recommended_action = str(runtime.get("recommendation") or "Verify runtime job table and owner-safe execution controls.")
        elif system_id == "governance":
            governance = mission_control_governance()
            data_coverage = 75 if governance.get("policies") else 25
            evidence_quality = 80 if governance.get("decisions") else 45
            functional_backend = 80
            integration_readiness = 70
            automation_readiness = 55
            operational_reliability = 75
            blockers = []
            source = "constitutional_governance"
            telemetry_freshness = str(governance.get("generated_at") or generated_at)
            recommended_action = "Keep owner-approval policy enforced for production writes."
        elif system_id == "build_history":
            blockers = ["Live GitHub deployment/build connector is not yet attached."]
            data_coverage = 35
            evidence_quality = 35
            functional_backend = 50
            integration_readiness = 20
            automation_readiness = 20
            operational_reliability = 40
            source = "repository_registry"
            telemetry_freshness = "static repository registry; connector credential missing"
            recommended_action = "Configure read-only GitHub/Render telemetry credentials server-side."
        elif system_id in {"grant_office", "partnership_generator", "recommendations", "health", "completeness", "integrations"}:
            functional_backend = 75 if system_id != "integrations" else 45
            data_coverage = 55 if system_id in {"recommendations", "health", "completeness"} else 35
            evidence_quality = 60 if system_id in {"recommendations", "health", "completeness"} else 35
            integration_readiness = 60 if system_id in {"recommendations", "health", "completeness"} else 25
            automation_readiness = 55 if system_id in {"recommendations", "health", "completeness"} else 35
            operational_reliability = 65 if system_id in {"recommendations", "health", "completeness"} else 40
            blockers = [] if system_id in {"recommendations", "health", "completeness"} else ["Needs deeper source-specific persistence telemetry."]
            telemetry_freshness = str(generated_at)
            recommended_action = "Use owner-authenticated BUILD-051 records after deployment." if system_id != "integrations" else "Configure only supported connector credentials; report unsupported integrations as not implemented."

        if not row and source_key in metric_rows and not metric.get("available"):
            blockers.append(f"No connected telemetry table for {definition['name']}.")

        completion = _score_completion(
            functional_backend=functional_backend,
            data_coverage=data_coverage,
            scientific_validation=scientific_validation,
            integration_readiness=integration_readiness,
            automation_readiness=automation_readiness,
            operational_reliability=operational_reliability,
        )
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
                summary=f"{definition['name']} is {status} at {completion}% completion from {source}. Data coverage {data_coverage}%, evidence quality {evidence_quality}%, integration readiness {integration_readiness}%.",
                metrics={
                    "source_metric": metric,
                    "database_connected": bool(metrics.get("database_connected")),
                    "scoring": {
                        "functional_backend": functional_backend,
                        "data_coverage": data_coverage,
                        "scientific_validation": scientific_validation,
                        "integration_readiness": integration_readiness,
                        "automation_readiness": automation_readiness,
                        "operational_reliability": operational_reliability,
                    },
                },
                data_coverage=data_coverage,
                evidence_quality=evidence_quality,
                automation_readiness=automation_readiness,
                integration_readiness=integration_readiness,
                operational_reliability=operational_reliability,
                active_jobs=active_jobs,
                failures=failures,
                recommended_action=recommended_action,
                source_record_counts=_source_counts(metric),
                telemetry_freshness=telemetry_freshness,
            )
        )
    return subsystems


def source_recommendations() -> list[dict[str, Any]]:
    return list(mission_control_recommendations().get("recommendations") or [])


def activation_matrix(subsystems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "state": _activation_status(ExecutiveSubsystem(**{key: item[key] for key in ExecutiveSubsystem.__dataclass_fields__ if key in item})),
            "source": item.get("source"),
            "completion": item.get("completion"),
            "blockers": item.get("blockers", []),
            "owner_required": item.get("owner_required", False),
            "recommended_action": item.get("recommended_action") or item.get("summary"),
        }
        for item in subsystems
    ]

