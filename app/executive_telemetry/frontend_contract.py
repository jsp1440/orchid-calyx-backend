from __future__ import annotations

from typing import Any


NAVIGATION = [
    "recommendations",
    "health",
    "completeness",
    "integrations",
    "inaturalist",
    "gbif",
    "world_plants_hassler",
    "eol_traitbank",
    "globi",
    "pollinator_datasets",
]


def _nav_identity(item_id: str) -> dict[str, str | None]:
    try:
        index = NAVIGATION.index(item_id)
    except ValueError:
        return {"previous": None, "current": item_id, "next": None}
    return {
        "previous": NAVIGATION[index - 1] if index > 0 else None,
        "current": item_id,
        "next": NAVIGATION[index + 1] if index < len(NAVIGATION) - 1 else None,
    }


def _safe_value(value: Any, unavailable: str = "unavailable") -> Any:
    if value is None or value == "" or value == "unknown":
        return unavailable
    return value


def _executive_panel(panel_id: str, title: str, state: dict[str, Any], intelligence: dict[str, Any]) -> dict[str, Any]:
    recommendation = intelligence.get("primary_recommendation") or state.get("recommendation_summary") or {}
    status = state.get("overall_health") if panel_id == "health" else state.get("integrations_status") if panel_id == "integrations" else "available"
    metric = state.get("overall_completeness") if panel_id == "completeness" else len(state.get("active_blockers") or []) if panel_id == "health" else len(intelligence.get("dependencies") or [])
    return {
        "id": panel_id,
        "title": title,
        "category_badges": ["Executive", "Telemetry"],
        "status": _safe_value(status),
        "narrative_summary": _safe_value(recommendation.get("recommendation"), "No live recommendation is currently available."),
        "next_action": _safe_value(recommendation.get("next_authorized_action"), "Review available evidence and restore unavailable sources."),
        "metric": metric,
        "target": 100 if panel_id == "completeness" else "not_applicable",
        "schedule": "continuous_read_only",
        "freshness": _safe_value(state.get("generated_at")),
        "approval_state": "read_only_advisory",
        "calyx_context": {
            "recommendation_signal": _safe_value(recommendation.get("signal") or recommendation.get("status")),
            "reason": _safe_value(recommendation.get("reason"), "No reason was supplied by the recommendation engine."),
            "confidence": float(recommendation.get("confidence") or 0.0),
        },
        "navigation": _nav_identity(panel_id),
    }


def _harvester_panel(item: dict[str, Any]) -> dict[str, Any]:
    source_id = str(item.get("source_id"))
    context = item.get("calyx_context") or {}
    return {
        "id": source_id,
        "title": _safe_value(item.get("title"), source_id),
        "category_badges": item.get("category_badges") or ["Harvester", "Telemetry"],
        "status": _safe_value(item.get("status")),
        "narrative_summary": _safe_value(item.get("narrative_summary"), "Telemetry source is unavailable."),
        "next_action": _safe_value(item.get("next_action"), "Restore the source and verify its latest governed heartbeat."),
        "metric": int(item.get("records_processed") or 0),
        "target": item.get("target_records") if item.get("target_records") is not None else "unavailable",
        "schedule": _safe_value(item.get("schedule")),
        "freshness": _safe_value(item.get("freshness")),
        "approval_state": _safe_value(item.get("approval_state"), "owner_authorization_required"),
        "calyx_context": {
            "recommendation_signal": _safe_value(context.get("recommendation_signal")),
            "reason": _safe_value(context.get("reason"), "No recommendation reason is available."),
            "confidence": float(context.get("confidence") or 0.0),
        },
        "completion_percentage": item.get("completion_percentage"),
        "duplicate_count": int(item.get("duplicate_count") or 0),
        "duplicate_rate": float(item.get("duplicate_rate") or 0.0),
        "throughput": item.get("throughput"),
        "queue_remaining": item.get("queue_remaining"),
        "estimated_completion": item.get("estimated_completion"),
        "allowed_actions": item.get("allowed_actions") or {},
        "provenance": item.get("provenance") or {},
        "navigation": _nav_identity(source_id),
    }


def build_frontend_contract(
    state: dict[str, Any],
    harvesters: list[dict[str, Any]],
    intelligence: dict[str, Any],
) -> dict[str, Any]:
    executive = [
        _executive_panel("recommendations", "Recommendations", state, intelligence),
        _executive_panel("health", "Health", state, intelligence),
        _executive_panel("completeness", "Completeness", state, intelligence),
        _executive_panel("integrations", "Integrations", state, intelligence),
    ]
    harvester_panels = [_harvester_panel(item) for item in harvesters if item.get("source_id") in NAVIGATION]
    panels = executive + harvester_panels
    return {
        "contract_version": "MISSION-CONTROL-TELEMETRY-001E",
        "generated_at": state.get("generated_at"),
        "panels": panels,
        "panel_index": {item["id"]: item for item in panels},
        "navigation_order": NAVIGATION,
        "placeholder_policy": {
            "unknown_forbidden": True,
            "unavailable_required_when_missing": True,
            "zero_allowed_only_for_observed_or_count_fields": True,
        },
        "readiness": {
            "frontend_redesign_required": False,
            "direct_field_population_supported": True,
            "missing_panel_ids": [item for item in NAVIGATION if item not in {panel["id"] for panel in panels}],
        },
        "governance": {
            "read_only": True,
            "does_not_publish": True,
            "does_not_grant_scientific_authority": True,
        },
    }
