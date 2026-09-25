"""Canonical Orchid Continuum mission context for autonomous regulation.

The human-readable philosophical authority remains:
- brain/philosophy/FOUNDING_CHARTER.md
- brain/philosophy/CONSTITUTION.md

This module provides a stable machine-readable operational directive derived
from those documents so runtime controllers and planners can carry the mission
without duplicating component-specific instructions.
"""

from __future__ import annotations

from typing import Any

MISSION_ID = "oc-mission-v1"
MISSION_STATEMENT = (
    "Orchid Continuum exists to build an evolving, trustworthy intelligence "
    "system for Orchidaceae that gathers and connects scientific knowledge, "
    "preserves evidence and uncertainty, discovers relationships and gaps, "
    "supports research and conservation, and transforms that knowledge into "
    "accurate, accessible, and inspiring experiences that help people "
    "understand, explore, and value orchids."
)
GUIDING_PRINCIPLE = (
    "The Orchid Continuum exists to cultivate understanding by revealing relationships."
)
NORTH_STAR_QUESTION = (
    "Does this help someone discover a meaningful relationship they could not see before?"
)

MISSION_OBJECTIVES = (
    "gather_and_connect_scientific_knowledge",
    "preserve_evidence_provenance_and_uncertainty",
    "discover_relationships_and_knowledge_gaps",
    "support_research_and_conservation",
    "create_accurate_accessible_inspiring_understanding",
    "continually_improve_without_losing_scientific_integrity",
)


def mission_context() -> dict[str, Any]:
    """Return the stable mission context carried by autonomous decisions."""
    return {
        "mission_id": MISSION_ID,
        "mission_statement": MISSION_STATEMENT,
        "guiding_principle": GUIDING_PRINCIPLE,
        "north_star_question": NORTH_STAR_QUESTION,
        "objectives": list(MISSION_OBJECTIVES),
        "authority": [
            "brain/philosophy/FOUNDING_CHARTER.md",
            "brain/philosophy/CONSTITUTION.md",
        ],
    }
