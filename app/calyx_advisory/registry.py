"""Calyx capability registry: the lenses Calyx evaluates the Continuum through."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Competency:
    key: str
    description: str
    inspects: tuple[str, ...]
    finding_kinds: tuple[str, ...]


COMPETENCIES: tuple[Competency, ...] = (
    Competency(
        "science-education",
        "Teaching scientific content, including contested science, without distorting it.",
        ("claims", "evidence_state", "uncertainty"),
        ("educational_gap", "teaching_opportunity"),
    ),
    Competency(
        "curriculum-instructional-design",
        "Sequencing content into pathways with objectives, prerequisites and tiers.",
        ("surfaces", "learning_pathways"),
        ("curriculum_gap",),
    ),
    Competency(
        "teaching-modalities",
        "Choosing between exposition, inquiry, worked example and investigation.",
        ("surfaces",),
        ("teaching_opportunity", "curriculum_gap"),
    ),
    Competency(
        "learning-progression-assessment",
        "Novice-to-expert progression and how understanding is checked.",
        ("learning_pathways", "assessments"),
        ("curriculum_gap",),
    ),
    Competency(
        "accessibility",
        "Perceivable, operable, understandable presentation for all learners.",
        ("surfaces",),
        ("accessibility_gap",),
    ),
    Competency(
        "scientific-communication",
        "Stating evidence, confidence and limits plainly to a stated audience.",
        ("claims", "surfaces"),
        ("educational_gap",),
    ),
    Competency(
        "information-architecture",
        "Structure, progressive disclosure and navigation of knowledge.",
        ("surfaces",),
        ("ux_gap",),
    ),
    Competency(
        "web-interaction-design",
        "Interaction patterns, cognitive load and educational UX.",
        ("surfaces",),
        ("ux_gap",),
    ),
)

#: Surfaces and artifacts Calyx may read. Anything else is out of scope.
INSPECTABLE: tuple[str, ...] = (
    "module_capability_registries",
    "reasoning_maps",
    "provenance",
    "uncertainty",
    "scientific_contradictions",
    "architecture_contracts",
    "ui_contracts",
    "learning_pathways",
    "educational_surfaces",
)


def competency(key: str) -> Competency:
    for item in COMPETENCIES:
        if item.key == key:
            return item
    raise KeyError(key)


def covered_kinds() -> frozenset[str]:
    return frozenset(kind for item in COMPETENCIES for kind in item.finding_kinds)
