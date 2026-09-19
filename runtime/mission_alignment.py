"""Deterministic mission-alignment admission policy for autonomous work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from runtime.mission_genome import MISSION_ID

DOMAIN_OBJECTIVES: dict[str, tuple[str, ...]] = {
    "Engineering": ("continually_improve_without_losing_scientific_integrity",),
    "Mission Control": (
        "preserve_evidence_provenance_and_uncertainty",
        "continually_improve_without_losing_scientific_integrity",
    ),
    "Cognitive": (
        "discover_relationships_and_knowledge_gaps",
        "create_accurate_accessible_inspiring_understanding",
    ),
    "Scientific": (
        "gather_and_connect_scientific_knowledge",
        "preserve_evidence_provenance_and_uncertainty",
    ),
    "Exploration": (
        "discover_relationships_and_knowledge_gaps",
        "support_research_and_conservation",
    ),
    "Narrative": ("create_accurate_accessible_inspiring_understanding",),
}


@dataclass(frozen=True)
class MissionAlignment:
    aligned: bool
    objectives: tuple[str, ...]
    reason: str
    mission_id: str = MISSION_ID

    def to_dict(self) -> dict[str, Any]:
        return {
            "aligned": self.aligned,
            "objectives": list(self.objectives),
            "reason": self.reason,
            "mission_id": self.mission_id,
        }


def evaluate_work_alignment(work: dict[str, Any]) -> MissionAlignment:
    """Classify work against the canonical OC mission without model inference."""
    domain = str(work.get("domain") or "").strip()
    action = str(work.get("next_action") or work.get("planned_action") or "").strip()
    objectives = DOMAIN_OBJECTIVES.get(domain, ())

    if not action:
        return MissionAlignment(
            aligned=False,
            objectives=objectives,
            reason="work has no concrete next action to evaluate",
        )

    if not objectives:
        return MissionAlignment(
            aligned=False,
            objectives=(),
            reason=f"domain is not mapped to an OC mission objective: {domain or 'missing'}",
        )

    return MissionAlignment(
        aligned=True,
        objectives=objectives,
        reason=f"{domain} work is explicitly mapped to canonical OC mission objectives",
    )
