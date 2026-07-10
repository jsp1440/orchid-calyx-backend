from __future__ import annotations

from typing import Any

WEIGHTS = {
    "scientific_impact": 0.18,
    "conservation_impact": 0.14,
    "research_impact": 0.12,
    "owner_value": 0.16,
    "dependency_blocking": 0.16,
    "risk": 0.08,
    "build_readiness": 0.08,
    "evidence_confidence": 0.05,
    "freshness": 0.03,
}

DOMAIN_IMPACT = {
    "knowledge_graph": (95, 80, 90),
    "atlas": (85, 90, 75),
    "literature": (80, 70, 90),
    "pollinators": (80, 85, 85),
    "mycorrhiza": (80, 85, 85),
    "vision_lab": (70, 60, 65),
    "grant_office": (65, 80, 70),
    "partnership_generator": (60, 70, 70),
    "harvesters": (75, 75, 75),
}


def score_priority(subsystem: dict[str, Any], dependents: list[str] | None = None) -> dict[str, Any]:
    dependents = dependents or []
    system_id = str(subsystem["id"])
    completion = int(subsystem.get("completion") or 0)
    blockers = list(subsystem.get("blockers") or [])
    confidence = float(subsystem.get("confidence") or 0.3)
    scientific, conservation, research = DOMAIN_IMPACT.get(system_id, (55, 50, 50))
    owner_value = 85 if subsystem.get("owner_required") else 45
    dependency_blocking = min(100, len(dependents) * 18 + len(blockers) * 12)
    risk = 100 - min(95, len(blockers) * 18 + (100 - completion) * 0.4)
    build_readiness = max(10, min(100, completion + confidence * 20))
    freshness = 70 if subsystem.get("last_updated") else 25

    factors = {
        "scientific_impact": scientific,
        "conservation_impact": conservation,
        "research_impact": research,
        "owner_value": owner_value,
        "dependency_blocking": dependency_blocking,
        "risk": risk,
        "build_readiness": build_readiness,
        "evidence_confidence": confidence * 100,
        "freshness": freshness,
    }
    score = round(sum(factors[key] * weight for key, weight in WEIGHTS.items()), 2)
    priority = "critical" if score >= 75 else "high" if score >= 60 else "medium" if score >= 42 else "low"
    return {"subsystem_id": system_id, "score": score, "priority": priority, "factors": factors, "dependents": dependents}


def ordered_priorities(subsystems: list[dict[str, Any]], reverse_dependencies: dict[str, list[str]]) -> list[dict[str, Any]]:
    scored = [
        {
            **score_priority(subsystem, reverse_dependencies.get(str(subsystem["id"]), [])),
            "title": subsystem["name"],
            "status": subsystem["status"],
            "blockers": subsystem.get("blockers", []),
        }
        for subsystem in subsystems
    ]
    return sorted(scored, key=lambda item: item["score"], reverse=True)

