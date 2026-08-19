from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any


def _id(prefix: str, payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:16]}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _text(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def matrix_identification_table(report: dict[str, Any]) -> dict[str, Any] | None:
    candidates = report.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        return None
    rows = []
    for rank, candidate in enumerate(candidates[:20], start=1):
        if not isinstance(candidate, dict):
            continue
        score = candidate.get("score")
        coverage = candidate.get("coverage")
        rows.append(
            {
                "rank": rank,
                "scientific_name": _text(candidate.get("scientific_name"), 300),
                "taxon_id": _text(candidate.get("taxon_id"), 200),
                "match_percent": round(float(score) * 100, 1)
                if isinstance(score, (int, float))
                else "",
                "coverage_percent": round(float(coverage) * 100, 1)
                if isinstance(coverage, (int, float))
                else "",
                "compared_weight": candidate.get("compared_weight")
                if isinstance(candidate.get("compared_weight"), (int, float))
                else "",
            }
        )
    if not rows:
        return None
    identity = {
        "rows": rows,
        "observation_count": report.get("observation_count"),
        "compared_character_count": report.get("compared_character_count"),
    }
    return {
        "id": _id("matrix-identification", identity),
        "kind": "table",
        "title": "Identification candidate ranking",
        "subtitle": (
            "Derived from the submitted observation/candidate matrix. Ranking supports "
            "review and does not assert a verified identification."
        ),
        "provenance": {
            "source_module": "matrix-identification",
            "source_id": _id("matrix-evaluation", identity),
            "generated": True,
            "evidence_status": "derived",
        },
        "payload": {
            "columns": [
                {"key": "rank", "label": "Rank"},
                {"key": "scientific_name", "label": "Candidate"},
                {"key": "taxon_id", "label": "Taxon ID"},
                {"key": "match_percent", "label": "Match %"},
                {"key": "coverage_percent", "label": "Coverage %"},
                {"key": "compared_weight", "label": "Compared weight"},
            ],
            "rows": rows,
        },
        "created_at": _now(),
    }
