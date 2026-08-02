"""Deterministic World Plants release comparison and crosswalk generation.

This module is side-effect free. It classifies exact, evidence-backed mappings
between two staged Michael Hassler / World Plants releases. Fuzzy similarity is
never used to authorize a mapping.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

from runtime.world_plants_ingest import WorldPlantsRow

_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class CrosswalkCandidate:
    previous_row: int
    current_row: int | None
    previous_name: str
    current_name: str | None
    classification: str
    confidence: str
    evidence: tuple[str, ...]
    automatic_acceptance: bool

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence"] = list(self.evidence)
        return result


@dataclass(frozen=True)
class ReleaseComparison:
    candidates: tuple[CrosswalkCandidate, ...]
    added_rows: tuple[int, ...]
    summary: dict[str, int]

    @property
    def ambiguous_count(self) -> int:
        return self.summary.get("ambiguous", 0)

    @property
    def promotion_blocked(self) -> bool:
        return self.ambiguous_count > 0 or self.summary.get("removed", 0) > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "added_rows": list(self.added_rows),
            "summary": dict(self.summary),
            "promotion_blocked": self.promotion_blocked,
            "fuzzy_matching_used": False,
            "owner_review_required": True,
        }


def normalize_text(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip()).casefold()


def normalized_name(row: WorldPlantsRow) -> str:
    return normalize_text(row.name)


def world_plants_number(row: WorldPlantsRow) -> str:
    return normalize_text(row.values.get("world_plants_number", ""))


def _index(rows: tuple[WorldPlantsRow, ...], key_fn) -> dict[str, list[WorldPlantsRow]]:
    result: dict[str, list[WorldPlantsRow]] = defaultdict(list)
    for row in rows:
        key = key_fn(row)
        if key:
            result[key].append(row)
    return result


def _classify(
    previous: WorldPlantsRow,
    current: WorldPlantsRow,
    evidence: tuple[str, ...],
) -> str:
    if previous.taxon_code != current.taxon_code:
        return "rank_change"
    if previous.name == current.name:
        return "unchanged"
    if normalize_text(previous.name) == normalize_text(current.name):
        return "authorship_or_format_change"
    previous_genus = previous.name.split(maxsplit=1)[0].casefold()
    current_genus = current.name.split(maxsplit=1)[0].casefold()
    if previous_genus != current_genus:
        return "genus_transfer"
    if "world_plants_number" in evidence:
        return "accepted_name_change"
    return "name_change"


def compare_and_crosswalk(
    previous: Iterable[WorldPlantsRow],
    current: Iterable[WorldPlantsRow],
) -> ReleaseComparison:
    """Build an exact-evidence crosswalk without fuzzy matching.

    Match priority:
    1. unique non-empty World Plants number;
    2. unique exact normalized name plus rank;
    3. otherwise unresolved or ambiguous and blocked for review.
    """

    previous_rows = tuple(previous)
    current_rows = tuple(current)
    current_by_number = _index(current_rows, world_plants_number)
    current_by_name_rank = _index(
        current_rows, lambda row: f"{row.taxon_code}|{normalized_name(row)}"
    )
    used_current_rows: set[int] = set()
    candidates: list[CrosswalkCandidate] = []
    summary: dict[str, int] = defaultdict(int)

    for old in previous_rows:
        matches: list[WorldPlantsRow] = []
        evidence: tuple[str, ...] = ()
        number = world_plants_number(old)
        if number:
            numbered = current_by_number.get(number, [])
            if len(numbered) == 1:
                matches = numbered
                evidence = ("world_plants_number",)
            elif len(numbered) > 1:
                matches = numbered
                evidence = ("duplicate_world_plants_number",)

        if not matches:
            key = f"{old.taxon_code}|{normalized_name(old)}"
            exact = current_by_name_rank.get(key, [])
            if exact:
                matches = exact
                evidence = ("normalized_name", "rank")

        if len(matches) == 1:
            new = matches[0]
            classification = _classify(old, new, evidence)
            automatic = classification in {"unchanged", "authorship_or_format_change"}
            confidence = "exact" if automatic else "authority_exact"
            candidates.append(
                CrosswalkCandidate(
                    previous_row=old.source_row_number,
                    current_row=new.source_row_number,
                    previous_name=old.name,
                    current_name=new.name,
                    classification=classification,
                    confidence=confidence,
                    evidence=evidence,
                    automatic_acceptance=automatic,
                )
            )
            used_current_rows.add(new.source_row_number)
            summary[classification] += 1
            continue

        if len(matches) > 1:
            candidates.append(
                CrosswalkCandidate(
                    previous_row=old.source_row_number,
                    current_row=None,
                    previous_name=old.name,
                    current_name=None,
                    classification="ambiguous",
                    confidence="blocked",
                    evidence=evidence,
                    automatic_acceptance=False,
                )
            )
            summary["ambiguous"] += 1
            continue

        candidates.append(
            CrosswalkCandidate(
                previous_row=old.source_row_number,
                current_row=None,
                previous_name=old.name,
                current_name=None,
                classification="removed",
                confidence="unresolved",
                evidence=(),
                automatic_acceptance=False,
            )
        )
        summary["removed"] += 1

    added = tuple(
        row.source_row_number
        for row in current_rows
        if row.source_row_number not in used_current_rows
    )
    summary["added"] = len(added)
    return ReleaseComparison(tuple(candidates), added, dict(summary))
