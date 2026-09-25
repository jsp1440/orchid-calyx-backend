"""Feed KG evidence-coverage research missions into the autonomy reserve.

Turns ``KnowledgeGapDiscoveryEngine.research_queue()`` missions built from the
knowledge graph (``runtime/evidence_coverage_gaps.py``) into
:func:`runtime.knowledge_gap_queue_bridge.evidence_gap_candidate` inputs: one
candidate per (example taxon, domain), with the taxon name read from the KG
taxon node and never invented, then plans them through the shared reserve
planner ``scripts.oc_backlog_refiller.plan_refill``.

Fail-closed: if the queue did not come from the live KG (the engine fell back
to its stored record), or taxon names cannot be read, zero candidates are
produced and the reason is stated. Stale-record gaps never become work.
Locality-gated domains are skipped entirely.
"""

from __future__ import annotations

from typing import Any

from runtime.evidence_coverage_gaps import (
    EvidenceCoverageGapSource,
    EvidenceCoverageUnavailable,
)
from runtime.knowledge_gap_discovery import KnowledgeGapDiscoveryEngine
from runtime.knowledge_gap_queue_bridge import (
    EVIDENCE_GAP_DOMAIN_LABELS,
    evidence_gap_candidate,
)
from scripts.oc_backlog_refiller import plan_refill

ADAPTER_SCHEMA = "oc.evidence-gap-reserve-adapter.v1"
#: At most this many candidates per pass, matching the reserve materializer.
MAX_CANDIDATES_PER_PASS = 3
RESEARCH_QUEUE_SCAN = 20
#: Gap priority label -> reserve priority (lower is planned first; 0 is reserved).
RESERVE_PRIORITY = {"CRITICAL": 1, "HIGH": 2, "MEDIUM": 3}


def evidence_gap_candidates(
    queue: dict[str, Any],
    source: EvidenceCoverageGapSource,
    *,
    cap: int = MAX_CANDIDATES_PER_PASS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Return ``(candidates, rejections, unavailable_reason)`` for one pass."""
    cap = max(0, min(int(cap), MAX_CANDIDATES_PER_PASS))
    freshness = queue.get("freshness") or {}
    if (
        queue.get("gap_source") != "evidence_coverage_kg"
        or freshness.get("stale") is not False
    ):
        reason = (
            "knowledge-graph evidence coverage unavailable; stored-record gaps are "
            f"never converted to work ({freshness.get('reason') or 'no reason recorded'})"
        )
        return [], [], reason

    pairs: list[tuple[str, str, str | None, int]] = []
    rejections: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in queue.get("queue") or []:
        mission = item.get("mission") or {}
        domain = str(mission.get("domain") or item.get("domain") or "")
        if mission.get("locality_gated") or domain not in EVIDENCE_GAP_DOMAIN_LABELS:
            rejections.append(
                {
                    "gap_id": item.get("gap_id"),
                    "domain": domain,
                    "reason": "locality_gated_domain_skipped"
                    if mission.get("locality_gated")
                    else "unsupported_evidence_domain",
                }
            )
            continue
        candidate_source = mission.get("candidate_source") or {}
        source_table = candidate_source.get("source_table")
        priority = RESERVE_PRIORITY.get(str(item.get("priority")), 4)
        for taxon_id in (mission.get("taxon_scope") or {}).get(
            "example_taxon_ids"
        ) or []:
            key = (str(taxon_id), domain)
            if key in seen:
                continue  # a higher-ranked gap already covers this (taxon, domain)
            seen.add(key)
            pairs.append((str(taxon_id), domain, source_table, priority))

    if not pairs:
        return [], rejections, None
    try:
        labels = source.taxon_labels([taxon_id for taxon_id, *_ in pairs])
    except EvidenceCoverageUnavailable as exc:
        return (
            [],
            rejections,
            f"taxon names unavailable from the knowledge graph ({exc})",
        )

    candidates: list[dict[str, Any]] = []
    for taxon_id, domain, source_table, priority in pairs:
        if len(candidates) >= cap:
            break
        name = labels.get(taxon_id)
        if not name:
            rejections.append(
                {
                    "taxon_id": taxon_id,
                    "domain": domain,
                    "reason": "taxon_name_unresolved",
                }
            )
            continue
        try:
            candidate = evidence_gap_candidate(
                taxon_id=taxon_id,
                taxon_name=name,
                domain=domain,
                candidate_source_table=source_table,
                priority=priority,
            )
            # Keeps gap-rank order among equal priorities in plan_refill.
            candidate["queue_rank"] = len(candidates)
            candidates.append(candidate)
        except ValueError as exc:
            rejections.append(
                {"taxon_id": taxon_id, "domain": domain, "reason": str(exc)}
            )
    return candidates, rejections, None


def plan_evidence_gap_refill(
    snapshot: dict[str, Any],
    source: EvidenceCoverageGapSource,
    *,
    engine: KnowledgeGapDiscoveryEngine | None = None,
    cap: int = MAX_CANDIDATES_PER_PASS,
    reserve_depth: int = 2,
    planner_ok: bool = True,
) -> dict[str, Any]:
    """Plan bounded reserve work from live KG evidence-coverage gaps."""
    engine = engine or KnowledgeGapDiscoveryEngine(kg_source=source)
    queue = engine.research_queue(limit=RESEARCH_QUEUE_SCAN)
    candidates, rejections, unavailable = evidence_gap_candidates(
        queue, source, cap=cap
    )
    result = plan_refill(
        snapshot, candidates, reserve_depth=reserve_depth, planner_ok=planner_ok
    )
    result.update(
        {
            "source_schema": ADAPTER_SCHEMA,
            "source_gap_source": queue.get("gap_source"),
            "source_candidate_count": len(candidates),
            "source_rejections": rejections,
            "source_unavailable_reason": unavailable,
            "source_cap": cap,
        }
    )
    return result
