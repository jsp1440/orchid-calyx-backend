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


def retrieval_table(retrieval: dict[str, Any]) -> dict[str, Any] | None:
    results = retrieval.get("results") or []
    if not isinstance(results, list) or not results:
        return None
    rows = []
    for index, item in enumerate(results[:20], start=1):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "rank": item.get("rank") or index,
                "title": _text(item.get("title") or item.get("object_type") or "Retrieved object", 180),
                "type": _text(item.get("object_type"), 80),
                "review": _text(item.get("review_state"), 80),
                "verification": _text(item.get("verification_state"), 80),
                "score": item.get("fused_score") if isinstance(item.get("fused_score"), (int, float)) else "",
            }
        )
    if not rows:
        return None
    return {
        "id": _id("retrieval", rows),
        "kind": "table",
        "title": "Retrieved Orchid Continuum objects",
        "subtitle": (
            f"{retrieval.get('total_eligible_results', len(rows))} eligible result(s); "
            f"showing up to {len(rows)}. Retrieval alone does not establish evidence status."
        ),
        "provenance": {
            "source_module": "evidence-retrieval",
            "source_id": _text(retrieval.get("ranking_configuration_version"), 120) or None,
            "generated": False,
            "evidence_status": "unknown",
        },
        "payload": {
            "columns": [
                {"key": "rank", "label": "Rank"},
                {"key": "title", "label": "Source / object"},
                {"key": "type", "label": "Type"},
                {"key": "review", "label": "Review"},
                {"key": "verification", "label": "Verification"},
                {"key": "score", "label": "Score"},
            ],
            "rows": rows,
        },
        "created_at": _now(),
    }


def mission_evidence_table(mission: dict[str, Any]) -> dict[str, Any] | None:
    supporting = mission.get("supporting_evidence") or []
    contradicting = mission.get("contradicting_evidence") or []
    rows = []
    for status, items in (("supporting", supporting), ("contradicting", contradicting)):
        if not isinstance(items, list):
            continue
        for item in items[:12]:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "status": status,
                    "candidate": _text(item.get("candidate_id"), 80),
                    "subject": _text(item.get("subject"), 160),
                    "predicate": _text(item.get("predicate"), 180),
                    "value": _text(item.get("value"), 240),
                }
            )
    if not rows:
        return None
    mission_id = _text(mission.get("mission_id"), 160)
    return {
        "id": _id("mission-evidence", {"mission_id": mission_id, "rows": rows}),
        "kind": "table",
        "title": "Brain mission evidence comparison",
        "subtitle": "Supporting and contradicting Candidate Knowledge remain distinct from conclusions.",
        "provenance": {
            "source_module": "brain-mission",
            "source_id": mission_id or None,
            "generated": False,
            "evidence_status": "evidence",
        },
        "payload": {
            "columns": [
                {"key": "status", "label": "Evidence role"},
                {"key": "candidate", "label": "Candidate"},
                {"key": "subject", "label": "Subject"},
                {"key": "predicate", "label": "Predicate"},
                {"key": "value", "label": "Value"},
            ],
            "rows": rows,
        },
        "created_at": _now(),
    }


def mission_gap_text(mission: dict[str, Any]) -> dict[str, Any] | None:
    missing = mission.get("missing_evidence") or []
    if not isinstance(missing, list) or not missing:
        return None
    mission_id = _text(mission.get("mission_id"), 160)
    body = "Evidence gaps identified by the governed Brain mission:\n\n" + "\n".join(
        f"• {_text(item, 400)}" for item in missing[:12]
    )
    return {
        "id": _id("mission-gaps", {"mission_id": mission_id, "missing": missing[:12]}),
        "kind": "text",
        "title": "Evidence gaps and uncertainty",
        "subtitle": "Missing evidence is displayed explicitly rather than filled by model memory.",
        "provenance": {
            "source_module": "brain-mission",
            "source_id": mission_id or None,
            "generated": True,
            "evidence_status": "derived",
        },
        "payload": {"body": body},
        "created_at": _now(),
    }


def grounded_workspace_outputs(
    *, retrieval: dict[str, Any] | None, mission: dict[str, Any] | None
) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    if isinstance(retrieval, dict):
        output = retrieval_table(retrieval)
        if output:
            outputs.append(output)
    if isinstance(mission, dict):
        for builder in (mission_evidence_table, mission_gap_text):
            output = builder(mission)
            if output:
                outputs.append(output)
    return outputs
