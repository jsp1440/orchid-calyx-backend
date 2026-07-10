from __future__ import annotations

from typing import Any


def explain_priority(priority: dict[str, Any]) -> str:
    factors = priority.get("factors") or {}
    strongest = sorted(factors.items(), key=lambda item: item[1], reverse=True)[:3]
    factor_text = ", ".join(f"{name}={round(value, 1)}" for name, value in strongest)
    return f"{priority['title']} ranks {priority['priority']} with score {priority['score']} because {factor_text}."


def attach_reasoning(priorities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**priority, "explanation": explain_priority(priority)} for priority in priorities]

