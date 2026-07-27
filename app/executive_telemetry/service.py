from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from runtime.executive.telemetry import activation_matrix, collect_subsystems, source_recommendations


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status_rank(status: str) -> int:
    return {
        "blocked": 5,
        "failed": 5,
        "unavailable": 5,
        "warning": 4,
        "planned": 3,
        "idle": 2,
        "healthy": 1,
        "complete": 1,
    }.get(status, 3)


def _overall_health(subsystems: list[dict[str, Any]]) -> str:
    if not subsystems:
        return "unavailable"
    worst = max((_status_rank(str(item.get("status") or "planned")) for item in subsystems), default=5)
    return {5: "degraded", 4: "warning", 3: "planned", 2: "idle", 1: "healthy"}[worst]


def _public_subsystem(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "category": item.get("category"),
        "status": item.get("status"),
        "health": item.get("health"),
        "completion": item.get("completion"),
        "summary": item.get("summary"),
        "last_updated": item.get("last_updated"),
        "telemetry_freshness": item.get("telemetry_freshness"),
    }


def build_executive_state(*, include_operations: bool = False) -> dict[str, Any]:
    generated_at = _now()
    partial_failures: list[dict[str, Any]] = []

    try:
        subsystem_models = collect_subsystems()
        subsystem_rows = [item.as_dict() for item in subsystem_models]
    except Exception as exc:  # pragma: no cover - deployment degradation path
        subsystem_rows = []
        partial_failures.append(
            {
                "source": "runtime.executive.telemetry.collect_subsystems",
                "status": "unavailable",
                "error": str(exc),
            }
        )

    try:
        recommendations = source_recommendations()
    except Exception as exc:  # pragma: no cover - deployment degradation path
        recommendations = []
        partial_failures.append(
            {
                "source": "runtime.executive.telemetry.source_recommendations",
                "status": "unavailable",
                "error": str(exc),
            }
        )

    blockers = sorted(
        {
            str(blocker)
            for item in subsystem_rows
            for blocker in (item.get("blockers") or [])
            if blocker
        }
    )
    completion_values = [int(item.get("completion") or 0) for item in subsystem_rows]
    completeness = round(sum(completion_values) / len(completion_values)) if completion_values else 0
    operational_rows = subsystem_rows if include_operations else [_public_subsystem(item) for item in subsystem_rows]

    recommendation_summary = recommendations[0] if recommendations else {
        "status": "unavailable",
        "recommendation": "Restore executive telemetry sources and retry.",
        "reason": "No recommendation source returned a usable result.",
        "confidence": 0.0,
    }

    response: dict[str, Any] = {
        "contract_version": "MISSION-CONTROL-TELEMETRY-001A",
        "generated_at": generated_at,
        "overall_health": _overall_health(subsystem_rows),
        "overall_completeness": completeness,
        "integrations_status": next(
            (item.get("status") for item in subsystem_rows if item.get("id") == "integrations"),
            "unavailable",
        ),
        "recommendation_summary": recommendation_summary,
        "active_blockers": blockers,
        "data_freshness": {
            str(item.get("id")): item.get("telemetry_freshness") or "unavailable"
            for item in subsystem_rows
        },
        "subsystems": operational_rows,
        "partial_failures": partial_failures,
        "provenance": {
            "source": "runtime.executive.telemetry",
            "evidence_mode": "live_or_truthful_degraded",
            "generated_at": generated_at,
        },
        "degraded": bool(partial_failures) or not subsystem_rows,
        "governance": {
            "public_safe": not include_operations,
            "operational_details_included": include_operations,
            "does_not_publish": True,
            "does_not_grant_scientific_authority": True,
        },
    }

    if include_operations:
        response["activation_matrix"] = activation_matrix(subsystem_rows)

    return response
