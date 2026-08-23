"""Reviewing a whole collection at once, without inventing a verdict per plant.

WHY A COLLECTION VIEW NEEDS ITS OWN RULES

A grower with two hundred plants cannot open two hundred dossiers. But a list
is a much more dangerous shape than a dossier: a reader scans it, sees no red,
and stops. On one plant `unassessable` is a paragraph they read. In a list it
is a grey row they skip.

So this refuses to produce a single sorted list of "plants needing attention".
It reports four disjoint groups, and the group a plant lands in says what kind
of statement is being made about it:

    outside        a recorded condition falls outside an evidenced bound
    conflicting    the evidence disagrees with itself about the bound
    within         everything comparable was compared, and was inside
    unassessed     nothing could be compared at all

`unassessed` is a first-class group, not a remainder. A collection where
nothing can be assessed produces an empty `outside` list, and a caller reading
only that would report a healthy collection on the strength of total ignorance.
The counts are stated so that cannot happen silently.

WHY IT COUNTS PLANTS AND NOT VARIABLES

One plant with three breaches is one plant to go and look at. Summing breaches
would rank a bench with a single badly-placed plant above a room of marginal
ones, which is a ranking nobody asked for and no evidence supports.

WHAT IT STILL REFUSES

No advice, no priority score, no "worst first". Which plant to deal with first
depends on what the grower can do, the season, and what else is on the bench —
none of which is here. Ordering by severity would be a recommendation wearing a
sort order.
"""

from __future__ import annotations

from typing import Any

__all__ = ["REVIEW_GROUPS", "build_collection_review"]

#: The groups a plant can land in. Disjoint and exhaustive.
REVIEW_GROUPS: tuple[str, ...] = ("outside", "conflicting", "within", "unassessed")


def _group_for(assessment: dict[str, Any]) -> str:
    """Which group one plant's assessment belongs to.

    Ordered by what a reader must not miss. A plant with one breach and four
    unassessable variables is a plant with a breach; filing it under
    `unassessed` because most of its variables were would bury the one fact
    that was established.
    """
    counts = assessment.get("counts") or {}
    if counts.get("outside"):
        return "outside"
    if counts.get("conflicting"):
        return "conflicting"
    if counts.get("within"):
        return "within"
    return "unassessed"


def build_collection_review(
    entries: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    """Group a collection's plants by what its assessments established.

    `entries` pairs each plant with its own placement assessment, already built
    by the per-plant path. Reusing that path rather than reimplementing the
    comparison here is deliberate: two comparison implementations disagree
    eventually, and the one a grower sees on the dossier must be the one the
    collection view summarises.
    """
    groups: dict[str, list[dict[str, Any]]] = {name: [] for name in REVIEW_GROUPS}
    source_unread = 0

    for plant, assessment in entries:
        group = _group_for(assessment)
        consulted = assessment.get("requirement_source_consulted", True) is not False
        if not consulted:
            source_unread += 1
        groups[group].append(
            {
                "plant_id": plant.get("id"),
                "accession_number": plant.get("accession_number"),
                "display_name": plant.get("display_name"),
                "accepted_scientific_name": plant.get("accepted_scientific_name"),
                # Carried per plant so a reader can see which breach was found
                # against an instrument and which against a typed-in number.
                "breaches": [
                    {"variable": row["variable"], "breached": row.get("breached") or []}
                    for row in assessment.get("assessments") or []
                    if row.get("outcome") == "outside"
                ],
                "requirement_source_consulted": consulted,
            }
        )

    counts = {name: len(rows) for name, rows in groups.items()}
    return {
        "groups": groups,
        "counts": counts,
        "plant_count": sum(counts.values()),
        # Stated rather than left to be read off an empty `outside` list. A
        # caller that sees no breaches must not conclude the collection is well
        # placed when nothing in it could be assessed.
        "anything_assessed": counts["outside"]
        + counts["conflicting"]
        + counts["within"]
        > 0,
        # How many plants were assessed against a knowledge store nobody could
        # read. Every one of those is `unassessed` for a reason that says
        # nothing about the plant or its taxon.
        "requirement_source_unread_for": source_unread,
        "is_scientific_evidence": False,
        "is_recommendation": False,
        "note": (
            "A grouping of comparisons, not a work list. Which plant to deal "
            "with first depends on what the grower can do, the season, and "
            "what else is on the bench, none of which is in this data."
        ),
    }
