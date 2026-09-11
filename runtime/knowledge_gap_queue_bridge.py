"""Bridge canonical Calyx knowledge gaps into deterministic reserve work.

This module does not execute research. It converts synthesis gaps from the
closed domain vocabulary into authorized objective candidates for the existing
reserve planner, which the frontend persistence plane already consumes.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from app.calyx_conversation.teaching_synthesis import (
    knowledge_gap_to_research_question,
)
from scripts.oc_backlog_refiller import plan_refill

_SCHEMA = "oc.knowledge-gap-reserve-source.v1"


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def knowledge_gap_candidate(
    *,
    taxon_id: str,
    taxon_name: str,
    domain: str,
    research_question: str | None = None,
    priority: int = 1,
) -> dict[str, Any]:
    """Return one authorized reserve candidate from a canonical synthesis gap.

    The research question is always derived server-side. If a caller supplies
    one, it must exactly match the canonical normalized question; this prevents
    arbitrary instructions from entering the autonomous work queue.
    """

    normalized_taxon_id = _normalize(taxon_id)
    normalized_taxon_name = " ".join(taxon_name.split())
    normalized_domain = _normalize(domain)
    if not normalized_taxon_id:
        raise ValueError("CANONICAL_TAXON_ID_REQUIRED")
    if not normalized_taxon_name:
        raise ValueError("TAXON_NAME_REQUIRED")

    canonical_question = knowledge_gap_to_research_question(
        normalized_domain,
        normalized_taxon_name,
    )
    if canonical_question is None:
        raise ValueError("UNSUPPORTED_SYNTHESIS_DOMAIN")

    if research_question is not None:
        supplied = " ".join(research_question.split())
        if supplied != canonical_question:
            raise ValueError("NON_CANONICAL_RESEARCH_QUESTION")

    identity = {
        "schema": _SCHEMA,
        "taxon_id": normalized_taxon_id,
        "domain": normalized_domain,
        "research_question": canonical_question,
    }
    fingerprint = _fingerprint(identity)
    objective_key = fingerprint[:24]

    return {
        "source_kind": "objective",
        "source_ref": f"calyx-synthesis-gap:{objective_key}",
        "title": (
            f"Research {normalized_domain.replace('_', ' ')} gap for "
            f"{normalized_taxon_name}"
        ),
        "material_fingerprint": fingerprint,
        "semantic_key": (
            f"calyx-synthesis-gap:{normalized_taxon_id}:{normalized_domain}"
        ),
        "priority": max(0, min(5, int(priority))),
        "dependencies": [],
        "protected_boundaries": [],
        "source_payload": {
            **identity,
            "taxon_name": normalized_taxon_name,
            "execution_mode": "bounded_research_mission",
            "review_required": True,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
            "taxonomy_mutation": False,
            "sensitive_locality_disclosure": False,
        },
    }


def plan_knowledge_gap_refill(
    snapshot: dict[str, Any],
    gaps: Iterable[dict[str, Any]],
    *,
    taxon_id: str,
    taxon_name: str,
    reserve_depth: int = 2,
    planner_ok: bool = True,
) -> dict[str, Any]:
    """Create a bounded reserve plan from valid canonical knowledge gaps.

    Invalid or caller-altered gaps fail closed and are reported as source
    rejections. Valid gaps continue through the shared dependency, protected
    boundary, fingerprint, semantic-key, and reserve-depth gates.
    """

    candidates: list[dict[str, Any]] = []
    source_rejections: list[dict[str, Any]] = []

    for index, gap in enumerate(gaps):
        if not isinstance(gap, dict):
            source_rejections.append(
                {"gap_index": index, "reason": "invalid_gap_contract"}
            )
            continue
        try:
            candidates.append(
                knowledge_gap_candidate(
                    taxon_id=taxon_id,
                    taxon_name=taxon_name,
                    domain=str(gap.get("domain") or ""),
                    research_question=gap.get("research_question"),
                    priority=int(gap.get("priority", 1)),
                )
            )
        except (TypeError, ValueError) as exc:
            source_rejections.append(
                {
                    "gap_index": index,
                    "domain": str(gap.get("domain") or ""),
                    "reason": str(exc),
                }
            )

    result = plan_refill(
        snapshot,
        candidates,
        reserve_depth=reserve_depth,
        planner_ok=planner_ok,
    )
    result["source_schema"] = _SCHEMA
    result["source_candidate_count"] = len(candidates)
    result["source_rejections"] = source_rejections
    return result
