"""Governed relationship-matrix projection and comparison utilities.

The engine projects supplied evidence assertions into a read-only matrix. It
preserves unknown, not-recorded, conflicting, present and absent as distinct
states and does not mutate the canonical graph.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Literal

RelationshipState = Literal[
    "present",
    "absent",
    "unknown",
    "not_recorded",
    "conflicting",
]

_ALLOWED_STATES: set[str] = {
    "present",
    "absent",
    "unknown",
    "not_recorded",
    "conflicting",
}


@dataclass(frozen=True)
class RelationshipAssertion:
    subject_id: str
    subject_label: str
    dimension: str
    object_id: str
    object_label: str
    state: RelationshipState
    confidence: float | None = None
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class MatrixCell:
    subject_id: str
    object_id: str
    state: RelationshipState
    assertion_count: int
    confidence: float | None
    provenance: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _validate(assertion: RelationshipAssertion) -> None:
    if not assertion.subject_id.strip() or not assertion.object_id.strip():
        raise ValueError("subject_id and object_id are required")
    if not assertion.dimension.strip():
        raise ValueError("dimension is required")
    if assertion.state not in _ALLOWED_STATES:
        raise ValueError(f"unsupported relationship state: {assertion.state}")
    if assertion.confidence is not None and not 0 <= assertion.confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")


def _collapse_states(assertions: list[RelationshipAssertion]) -> RelationshipState:
    states = {item.state for item in assertions}
    if "conflicting" in states or ({"present", "absent"} <= states):
        return "conflicting"
    if "present" in states:
        return "present"
    if "absent" in states:
        return "absent"
    if "unknown" in states:
        return "unknown"
    return "not_recorded"


def _mean_confidence(assertions: list[RelationshipAssertion]) -> float | None:
    values = [item.confidence for item in assertions if item.confidence is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def build_relationship_matrix(
    assertions: list[RelationshipAssertion],
    *,
    dimension: str,
    subject_ids: list[str] | None = None,
    object_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic read-only matrix for one relationship dimension."""
    selected = [item for item in assertions if item.dimension == dimension]
    for assertion in selected:
        _validate(assertion)

    subject_labels = {item.subject_id: item.subject_label for item in selected}
    object_labels = {item.object_id: item.object_label for item in selected}
    subjects = sorted(set(subject_ids or subject_labels), key=lambda value: (subject_labels.get(value, value).casefold(), value))
    objects = sorted(set(object_ids or object_labels), key=lambda value: (object_labels.get(value, value).casefold(), value))

    grouped: dict[tuple[str, str], list[RelationshipAssertion]] = defaultdict(list)
    for assertion in selected:
        grouped[(assertion.subject_id, assertion.object_id)].append(assertion)

    cells: list[dict[str, Any]] = []
    state_counts = {state: 0 for state in sorted(_ALLOWED_STATES)}
    for subject_id in subjects:
        for object_id in objects:
            evidence = grouped.get((subject_id, object_id), [])
            state: RelationshipState = _collapse_states(evidence) if evidence else "not_recorded"
            state_counts[state] += 1
            provenance = [item.provenance for item in evidence if item.provenance is not None]
            cells.append(
                MatrixCell(
                    subject_id=subject_id,
                    object_id=object_id,
                    state=state,
                    assertion_count=len(evidence),
                    confidence=_mean_confidence(evidence),
                    provenance=provenance,
                ).as_dict()
            )

    return {
        "dimension": dimension,
        "subjects": [
            {"id": subject_id, "label": subject_labels.get(subject_id, subject_id)}
            for subject_id in subjects
        ],
        "objects": [
            {"id": object_id, "label": object_labels.get(object_id, object_id)}
            for object_id in objects
        ],
        "cells": cells,
        "state_counts": state_counts,
        "read_only": True,
        "canonical_graph_mutation": False,
        "disclaimer": (
            "Not-recorded, unknown, conflicting and absent are distinct states. "
            "A blank evidence record is never interpreted as biological absence."
        ),
    }


def compare_subjects(matrix: dict[str, Any], left_subject_id: str, right_subject_id: str) -> dict[str, Any]:
    """Compare two matrix rows without collapsing epistemic states."""
    by_pair = {
        (cell["subject_id"], cell["object_id"]): cell
        for cell in matrix.get("cells", [])
    }
    comparisons: list[dict[str, Any]] = []
    shared_present = 0
    disagreements = 0
    for obj in matrix.get("objects", []):
        object_id = obj["id"]
        left = by_pair.get((left_subject_id, object_id), {"state": "not_recorded"})
        right = by_pair.get((right_subject_id, object_id), {"state": "not_recorded"})
        left_state = left["state"]
        right_state = right["state"]
        if left_state == right_state == "present":
            shared_present += 1
        if {left_state, right_state} == {"present", "absent"}:
            disagreements += 1
        comparisons.append(
            {
                "object_id": object_id,
                "object_label": obj.get("label", object_id),
                "left_state": left_state,
                "right_state": right_state,
                "same_state": left_state == right_state,
            }
        )
    return {
        "left_subject_id": left_subject_id,
        "right_subject_id": right_subject_id,
        "shared_present": shared_present,
        "present_absent_disagreements": disagreements,
        "comparisons": comparisons,
        "read_only": True,
    }
