from __future__ import annotations

from typing import Any


def executive_summary(state: dict[str, Any]) -> dict[str, Any]:
    subsystems = state["subsystems"]
    priorities = state["priorities"]
    healthy = [item for item in subsystems if item["status"] == "healthy"]
    blocked = [item for item in subsystems if item["status"] in {"blocked", "planned"} or item.get("blockers")]
    owner = [item for item in subsystems if item.get("owner_required")]
    confidence_values = [float(item.get("confidence") or 0) for item in subsystems]
    confidence = round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0
    top = priorities[0] if priorities else None
    return {
        "executive_summary": f"{len(healthy)}/{len(subsystems)} executive subsystems are healthy. {len(blocked)} have blockers and {len(owner)} need owner attention.",
        "system_health": {
            "healthy": len(healthy),
            "blocked": len(blocked),
            "owner_required": len(owner),
            "total": len(subsystems),
        },
        "completed": [item["name"] for item in healthy],
        "changed": state.get("changes", []),
        "blocked": [item["name"] for item in blocked],
        "needs_owner": [item["name"] for item in owner],
        "needs_partner": [item["name"] for item in blocked if item["id"] in {"partnership_generator", "integrations", "grant_office"}],
        "highest_priority": top,
        "recommended_next_build": top["title"] if top else "No priority available",
        "confidence": confidence,
    }


def executive_briefing(state: dict[str, Any]) -> dict[str, Any]:
    summary = executive_summary(state)
    return {
        "title": "Calyx Executive Intelligence Briefing",
        "generated_at": state["generated_at"],
        **summary,
        "recommendations": state["recommendations"][:5],
    }

