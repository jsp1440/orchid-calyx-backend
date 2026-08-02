"""World Plants (Michael Hassler) release ingestion contracts.

This module is deliberately side-effect free. It parses the 22-field pipe-delimited
WorldOrchids release, preserves raw source values, produces validation findings,
and compares two releases. Database staging and canonical promotion remain
separate owner-gated operations.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable

SOURCE_SYSTEM = "world_plants_hassler"
EXPECTED_WIDTH = 22
BASE_COLUMNS = (
    "taxon_code",
    "world_plants_number",
    "name",
    "literature",
    "trivial_name",
    "distribution",
    "synonyms_raw",
    "status_raw",
    "remarks",
    "conservation_status",
)
PHOTO_COLUMNS = tuple(
    value
    for index in range(1, 5)
    for value in (f"photo_{index}", f"orientation_{index}", f"author_{index}")
)
COLUMNS = BASE_COLUMNS + PHOTO_COLUMNS
RANK_CODES = frozenset({"F", "SF", "T", "ST", "G", "S", "SS", "V", "FM"})


@dataclass(frozen=True)
class WorldPlantsSnapshot:
    version_label: str
    acquired_at: str
    filename: str
    sha256: str
    row_count: int
    source_system: str = SOURCE_SYSTEM

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WorldPlantsRow:
    source_row_number: int
    values: dict[str, str]

    @property
    def taxon_code(self) -> str:
        return self.values["taxon_code"]

    @property
    def name(self) -> str:
        return self.values["name"]

    @property
    def identity_key(self) -> tuple[str, str]:
        return (self.taxon_code, self.name)

    def photos(self) -> tuple[dict[str, str], ...]:
        result: list[dict[str, str]] = []
        for index in range(1, 5):
            photo = self.values[f"photo_{index}"]
            orientation = self.values[f"orientation_{index}"]
            author = self.values[f"author_{index}"]
            if photo or orientation or author:
                result.append(
                    {
                        "slot": str(index),
                        "photo": photo,
                        "orientation": orientation,
                        "author": author,
                    }
                )
        return tuple(result)


@dataclass(frozen=True)
class ParseResult:
    rows: tuple[WorldPlantsRow, ...]
    issues: tuple[dict[str, Any], ...]
    source_encoding: str
    rank_counts: dict[str, int]

    def summary(self) -> dict[str, Any]:
        return {
            "rows": len(self.rows),
            "issues": len(self.issues),
            "source_encoding": self.source_encoding,
            "rank_counts": dict(self.rank_counts),
            "photo_references": sum(len(row.photos()) for row in self.rows),
        }


@dataclass(frozen=True)
class ReleaseDelta:
    added: tuple[tuple[str, str], ...]
    removed: tuple[tuple[str, str], ...]
    unchanged: int
    duplicate_keys_new: tuple[tuple[str, str], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": [list(item) for item in self.added],
            "removed": [list(item) for item in self.removed],
            "unchanged": self.unchanged,
            "duplicate_keys_new": [list(item) for item in self.duplicate_keys_new],
            "promotion_allowed": not self.duplicate_keys_new,
            "owner_approval_required": True,
        }


def file_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def decode_release(payload: bytes) -> tuple[str, str]:
    """Decode without losing bytes; prefer UTF-8 and fall back to Latin-1."""
    try:
        return payload.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return payload.decode("latin-1"), "latin-1"


def parse_world_orchids_release(payload: bytes) -> ParseResult:
    text, encoding = decode_release(payload)
    reader = csv.reader(io.StringIO(text), delimiter="|")
    header = next(reader, None)
    issues: list[dict[str, Any]] = []
    if header is None:
        return ParseResult((), ({"reason": "empty_file"},), encoding, {})
    if len(header) != 13:
        issues.append({"reason": "unexpected_header_width", "actual": len(header)})

    rows: list[WorldPlantsRow] = []
    rank_counts: Counter[str] = Counter()
    for source_row_number, raw in enumerate(reader, start=2):
        if not raw or not any(value.strip() for value in raw):
            continue
        if len(raw) != EXPECTED_WIDTH:
            issues.append(
                {
                    "reason": "unexpected_row_width",
                    "source_row_number": source_row_number,
                    "actual": len(raw),
                    "expected": EXPECTED_WIDTH,
                }
            )
            continue
        normalized = {
            column: html.unescape(value.strip()) for column, value in zip(COLUMNS, raw)
        }
        code = normalized["taxon_code"].upper()
        normalized["taxon_code"] = code
        if code not in RANK_CODES:
            issues.append(
                {
                    "reason": "unknown_rank_code",
                    "source_row_number": source_row_number,
                    "value": code,
                }
            )
        if not normalized["name"]:
            issues.append(
                {"reason": "missing_name", "source_row_number": source_row_number}
            )
            continue
        rank_counts[code] += 1
        rows.append(WorldPlantsRow(source_row_number, normalized))

    return ParseResult(tuple(rows), tuple(issues), encoding, dict(rank_counts))


def build_snapshot(
    payload: bytes,
    *,
    version_label: str,
    acquired_at: str,
    filename: str,
) -> WorldPlantsSnapshot:
    parsed = parse_world_orchids_release(payload)
    return WorldPlantsSnapshot(
        version_label=version_label,
        acquired_at=acquired_at,
        filename=filename,
        sha256=file_sha256(payload),
        row_count=len(parsed.rows),
    )


def compare_releases(
    previous: Iterable[WorldPlantsRow],
    current: Iterable[WorldPlantsRow],
) -> ReleaseDelta:
    previous_keys = {row.identity_key for row in previous}
    current_rows = tuple(current)
    current_counter = Counter(row.identity_key for row in current_rows)
    current_keys = set(current_counter)
    return ReleaseDelta(
        added=tuple(sorted(current_keys - previous_keys)),
        removed=tuple(sorted(previous_keys - current_keys)),
        unchanged=len(previous_keys & current_keys),
        duplicate_keys_new=tuple(
            sorted(key for key, count in current_counter.items() if count > 1)
        ),
    )


def promotion_plan(snapshot: WorldPlantsSnapshot, delta: ReleaseDelta) -> dict[str, Any]:
    """Return a non-executing, owner-gated promotion plan."""
    return {
        "snapshot": snapshot.as_dict(),
        "delta": delta.as_dict(),
        "steps": [
            "register_immutable_source_snapshot",
            "load_versioned_staging_rows",
            "parse_and_preserve_synonym_assertions",
            "generate_old_to_new_taxon_crosswalk",
            "manual_review_of_ambiguous_mappings",
            "owner_approval",
            "atomic_canonical_release_promotion",
            "rebuild_and_verify_downstream_relationships",
        ],
        "automatic_promotion": False,
        "automatic_deletion": False,
        "rollback_required": True,
    }
