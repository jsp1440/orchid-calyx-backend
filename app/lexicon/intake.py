from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Any

from .intake_seed import (
    POLICY,
    RELEASE,
    SOURCE_FILE,
    SOURCE_SHA256,
    SOURCE_SHEET,
    SUMMARY,
    csv_text,
)

EXPECTED_FIELDS = (
    "glossary_id",
    "term",
    "category",
    "priority",
    "definition_state",
    "concept_intake_state",
    "figure_state",
    "figure_exists",
    "existing_asset",
    "match_confidence",
    "prompt_id",
    "target_filename",
    "workflow_status",
)


def _normalize(row: dict[str, str]) -> dict[str, Any]:
    return {
        **row,
        "priority": int(row["priority"] or 0),
        "match_confidence": float(row["match_confidence"] or 0),
    }


def load_items() -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(csv_text()))
    if tuple(reader.fieldnames or ()) != EXPECTED_FIELDS:
        raise RuntimeError("LEXICON_INTAKE_HEADER_MISMATCH")
    rows = [_normalize(dict(row)) for row in reader]
    if len(rows) != SUMMARY["terms"]:
        raise RuntimeError("LEXICON_INTAKE_ROW_COUNT_MISMATCH")
    ids = [row["glossary_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise RuntimeError("LEXICON_INTAKE_DUPLICATE_GLOSSARY_ID")
    return rows


def validate_manifest() -> dict[str, Any]:
    rows = load_items()
    definition_counts = Counter(row["definition_state"] for row in rows)
    concept_counts = Counter(row["concept_intake_state"] for row in rows)
    figure_exists_counts = Counter(row["figure_exists"] for row in rows)
    figure_counts = Counter(row["figure_state"] for row in rows)

    actual = {
        "terms": len(rows),
        "definitions_present": definition_counts["PRESENT"],
        "placeholder_definitions": definition_counts["PLACEHOLDER"],
        "existing_exact_assets": figure_exists_counts["YES"],
        "probable_assets": figure_exists_counts["PROBABLE / VERIFY"],
        "missing_assets": figure_exists_counts["NO"],
        "ready_for_concept_review": concept_counts["READY_FOR_CONCEPT_REVIEW"],
        "blocked_definition": concept_counts["BLOCKED_DEFINITION"],
        "figure_generation_hold": figure_counts["FIGURE_GENERATION_HOLD"],
    }
    if actual != SUMMARY:
        raise RuntimeError(f"LEXICON_INTAKE_SUMMARY_MISMATCH:{actual}")
    return {
        "release": RELEASE,
        "source_file": SOURCE_FILE,
        "source_sheet": SOURCE_SHEET,
        "source_sha256": SOURCE_SHA256,
        "summary": actual,
        "policy": POLICY,
        "valid": True,
    }


def filter_items(
    *,
    q: str | None = None,
    concept_intake_state: str | None = None,
    figure_state: str | None = None,
    priority: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = load_items()
    needle = q.casefold().strip() if q else None
    result: list[dict[str, Any]] = []
    for row in rows:
        if concept_intake_state and row["concept_intake_state"] != concept_intake_state:
            continue
        if figure_state and row["figure_state"] != figure_state:
            continue
        if priority is not None and row["priority"] != priority:
            continue
        if needle and needle not in f"{row['term']} {row['glossary_id']} {row['category']}".casefold():
            continue
        result.append(row)
        if len(result) >= limit:
            break
    return result


def get_item(glossary_id: str) -> dict[str, Any] | None:
    target = glossary_id.casefold().strip()
    return next((row for row in load_items() if row["glossary_id"].casefold() == target), None)
