"""Parse embedded World Plants synonym strings into reviewable assertions.

The raw source string is always retained. Parsing is conservative: uncertain or
malformed fragments are routed to review and are never published automatically.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from runtime.world_plants_ingest import WorldPlantsRow

_CITATION_RE = re.compile(r"^(?P<name>.*?)(?:\s*\[(?P<citation>[^\]]+)\])?\s*$")
_SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SynonymAssertion:
    source_row_number: int
    accepted_name: str
    synonym_name: str
    citation_fragment: str | None
    raw_fragment: str
    parser_version: str = "world-plants-synonyms-001"
    requires_review: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SynonymParseResult:
    raw_text: str
    assertions: tuple[SynonymAssertion, ...]
    issues: tuple[dict[str, Any], ...]

    def summary(self) -> dict[str, Any]:
        return {
            "assertions": len(self.assertions),
            "issues": len(self.issues),
            "automatic_publication": False,
            "manual_review_required": True,
        }


def _normalize(value: str) -> str:
    return _SPACE_RE.sub(" ", value.strip())


def parse_synonym_assertions(row: WorldPlantsRow) -> SynonymParseResult:
    raw = row.values.get("synonyms_raw", "")
    if not raw.strip():
        return SynonymParseResult(raw, (), ())

    assertions: list[SynonymAssertion] = []
    issues: list[dict[str, Any]] = []
    seen: set[str] = set()

    fragments = raw.split("=")
    for position, fragment in enumerate(fragments):
        cleaned = _normalize(fragment)
        if not cleaned:
            continue
        match = _CITATION_RE.match(cleaned)
        if match is None:
            issues.append(
                {
                    "reason": "unparseable_fragment",
                    "source_row_number": row.source_row_number,
                    "position": position,
                    "raw_fragment": fragment,
                }
            )
            continue

        synonym_name = _normalize(match.group("name") or "")
        citation = _normalize(match.group("citation") or "") or None
        if not synonym_name:
            issues.append(
                {
                    "reason": "missing_synonym_name",
                    "source_row_number": row.source_row_number,
                    "position": position,
                }
            )
            continue

        key = synonym_name.casefold()
        if key == row.name.casefold():
            issues.append(
                {
                    "reason": "self_synonym",
                    "source_row_number": row.source_row_number,
                    "synonym_name": synonym_name,
                }
            )
        if key in seen:
            issues.append(
                {
                    "reason": "duplicate_synonym_assertion",
                    "source_row_number": row.source_row_number,
                    "synonym_name": synonym_name,
                }
            )
            continue
        seen.add(key)
        assertions.append(
            SynonymAssertion(
                source_row_number=row.source_row_number,
                accepted_name=row.name,
                synonym_name=synonym_name,
                citation_fragment=citation,
                raw_fragment=fragment,
            )
        )

    if raw.strip() and not assertions:
        issues.append(
            {
                "reason": "no_assertions_extracted",
                "source_row_number": row.source_row_number,
            }
        )
    return SynonymParseResult(raw, tuple(assertions), tuple(issues))


def parse_release_synonyms(rows: tuple[WorldPlantsRow, ...]) -> dict[str, Any]:
    results = tuple(parse_synonym_assertions(row) for row in rows)
    assertions = [item.as_dict() for result in results for item in result.assertions]
    issues = [issue for result in results for issue in result.issues]
    return {
        "assertions": assertions,
        "issues": issues,
        "rows_with_synonyms": sum(bool(result.raw_text.strip()) for result in results),
        "automatic_publication": False,
        "manual_review_required": True,
    }
