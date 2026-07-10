from __future__ import annotations

from typing import Any


def recommendation_for_priority(priority: dict[str, Any], subsystem: dict[str, Any]) -> dict[str, Any] | None:
    evidence = []
    if subsystem.get("source"):
        evidence.append(f"Telemetry source: {subsystem['source']}")
    if subsystem.get("blockers"):
        evidence.extend([f"Blocker: {item}" for item in subsystem["blockers"][:3]])
    evidence.append(f"Priority score: {priority['score']}")
    if not evidence:
        return None
    return {
        "id": f"exec-{subsystem['id']}",
        "title": f"Advance {subsystem['name']}",
        "reason": subsystem.get("summary"),
        "evidence": evidence,
        "confidence": subsystem.get("confidence"),
        "expected_benefit": "Improves executive readiness and unblocks dependent Mission Control views.",
        "dependencies": subsystem.get("dependencies", []),
        "risk": "medium" if subsystem.get("owner_required") else "low",
        "estimated_effort": "medium" if priority["score"] >= 60 else "small",
        "owner_action": "Review blockers and approve the next backend/frontend build scope." if subsystem.get("owner_required") else "Monitor telemetry.",
        "constitution_reference": "Owner authorization required for production writes; recommendations are read-only.",
        "priority": priority["priority"],
        "score": priority["score"],
    }


def generate_recommendations(priorities: list[dict[str, Any]], subsystems: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    by_id = {str(item["id"]): item for item in subsystems}
    recommendations = []
    for priority in priorities:
        subsystem = by_id.get(str(priority["subsystem_id"]))
        if not subsystem:
            continue
        recommendation = recommendation_for_priority(priority, subsystem)
        if recommendation:
            recommendations.append(recommendation)
        if len(recommendations) >= limit:
            break
    return recommendations

