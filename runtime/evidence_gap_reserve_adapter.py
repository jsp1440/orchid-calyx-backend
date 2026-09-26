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
#: Keyset page size when paging past a domain's held example taxa.
LACKING_PAGE_SIZE = 10
#: Hard bound on taxa scanned past the examples, per domain per pass.
MAX_PAGED_TAXA_PER_DOMAIN = 50


def _admit(
    candidates: list[dict[str, Any]],
    rejections: list[dict[str, Any]],
    held_fingerprints: frozenset[str] | set[str],
    *,
    taxon_id: str,
    name: str | None,
    domain: str,
    source_table: str | None,
    priority: int,
) -> str:
    """Append one candidate or one rejection; return the outcome label."""
    if not name:
        rejections.append(
            {"taxon_id": taxon_id, "domain": domain, "reason": "taxon_name_unresolved"}
        )
        return "taxon_name_unresolved"
    try:
        candidate = evidence_gap_candidate(
            taxon_id=taxon_id,
            taxon_name=name,
            domain=domain,
            candidate_source_table=source_table,
            priority=priority,
        )
    except ValueError as exc:
        rejections.append({"taxon_id": taxon_id, "domain": domain, "reason": str(exc)})
        return "invalid"
    if candidate["material_fingerprint"] in held_fingerprints:
        rejections.append(
            {"taxon_id": taxon_id, "domain": domain, "reason": "already_held_by_caller"}
        )
        return "already_held_by_caller"
    # Keeps gap-rank order among equal priorities in plan_refill.
    candidate["queue_rank"] = len(candidates)
    candidates.append(candidate)
    return "candidate"


def _page_past_held_examples(
    source: Any,
    candidates: list[dict[str, Any]],
    rejections: list[dict[str, Any]],
    held_fingerprints: frozenset[str] | set[str],
    *,
    cap: int,
    domain_gaps: dict[str, tuple[str | None, int, list[str]]],
    outcomes: dict[str, dict[str, int]],
    seen: set[tuple[str, str]],
) -> None:
    """Continue past a domain's example taxa once the caller holds all of them.

    A gap exposes only its first ``MAX_EXAMPLE_TAXA`` lacking taxa (source_pk
    order). A name-only lookup never writes to the KG, so once missions were
    filed for all five, the same five stayed "lacking" and every pass returned
    ``queue_empty_healthy`` (production, 2026-09-25, nomenclature). Pages the
    same lacking-taxa predicate forward, read-only and bounded by
    ``MAX_PAGED_TAXA_PER_DOMAIN`` per domain per pass. Only domains whose
    whole-domain gap was considered (never locality-gated, always within the
    ``domains`` filter), in gap-rank order, and which produced no candidate
    while at least one example was already held.
    """
    pager = getattr(source, "domain_lacking_taxa", None)
    if not callable(pager):
        return
    for domain, (source_table, priority, examples) in domain_gaps.items():
        if len(candidates) >= cap:
            return
        tally = outcomes.get(domain) or {}
        if tally.get("candidate") or not tally.get("already_held_by_caller"):
            continue
        after: str | None = examples[-1]  # examples arrive in KG source_pk order
        scanned = 0
        while len(candidates) < cap and scanned < MAX_PAGED_TAXA_PER_DOMAIN:
            limit = min(LACKING_PAGE_SIZE, MAX_PAGED_TAXA_PER_DOMAIN - scanned)
            try:
                page = [
                    str(t)
                    for t in pager(domain, after_source_pk=after, limit=limit)
                ][:limit]
                fresh = [t for t in page if (t, domain) not in seen]
                labels = source.taxon_labels(fresh) if fresh else {}
            except EvidenceCoverageUnavailable as exc:
                rejections.append(
                    {
                        "domain": domain,
                        "reason": "lacking_taxa_unavailable",
                        "detail": str(exc),
                    }
                )
                break
            if not page:
                break
            after = page[-1]
            scanned += len(page)
            for taxon_id in fresh:
                if len(candidates) >= cap:
                    break
                seen.add((taxon_id, domain))
                _admit(
                    candidates,
                    rejections,
                    held_fingerprints,
                    taxon_id=taxon_id,
                    name=labels.get(taxon_id),
                    domain=domain,
                    source_table=source_table,
                    priority=priority,
                )
            if len(page) < limit:
                break  # no further lacking taxa in this domain


def evidence_gap_candidates(
    queue: dict[str, Any],
    source: EvidenceCoverageGapSource,
    *,
    cap: int = MAX_CANDIDATES_PER_PASS,
    held_fingerprints: frozenset[str] | set[str] = frozenset(),
    domains: frozenset[str] | set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Return ``(candidates, rejections, unavailable_reason)`` for one pass.

    ``held_fingerprints`` are material fingerprints the caller already filed.
    They are skipped *before* the per-pass cap is applied: the cap bounds new
    work, and spending it on candidates ``plan_refill`` will only reject as
    duplicates made every pass after the first three missions plan nothing
    (``queue_empty_healthy`` on 2026-09-25 while taxa 1000 and 10000 still had
    no nomenclature evidence).

    ``domains`` restricts the pass to the evidence domains the caller can
    execute; ``None`` means every supported domain. Unrequested domains are
    skipped *before* the taxon-label lookup and the per-pass cap, for the same
    reason: missions the caller cannot run must not crowd out ones it can
    (three morphology missions were filed on 2026-09-25 although only
    nomenclature had an executor).

    When the cap is not reached and a considered domain's example taxa were all
    held by the caller, its lacking taxa are paged past the examples
    (read-only, bounded); see :func:`_page_past_held_examples`.
    """
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
    #: domain -> (source_table, priority, example ids) of its whole-domain gap,
    #: the one whose examples are the first lacking taxa in source_pk order.
    domain_gaps: dict[str, tuple[str | None, int, list[str]]] = {}
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
        if domains is not None and domain not in domains:
            rejections.append(
                {
                    "gap_id": item.get("gap_id"),
                    "domain": domain,
                    "reason": "domain_not_requested",
                }
            )
            continue
        candidate_source = mission.get("candidate_source") or {}
        source_table = candidate_source.get("source_table")
        priority = RESERVE_PRIORITY.get(str(item.get("priority")), 4)
        examples = [
            str(taxon_id)
            for taxon_id in (mission.get("taxon_scope") or {}).get("example_taxon_ids")
            or []
        ]
        if not source_table and examples:
            domain_gaps.setdefault(domain, (None, priority, examples))
        for taxon_id in examples:
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
    outcomes: dict[str, dict[str, int]] = {}
    for taxon_id, domain, source_table, priority in pairs:
        if len(candidates) >= cap:
            break
        outcome = _admit(
            candidates,
            rejections,
            held_fingerprints,
            taxon_id=taxon_id,
            name=labels.get(taxon_id),
            domain=domain,
            source_table=source_table,
            priority=priority,
        )
        tally = outcomes.setdefault(domain, {})
        tally[outcome] = tally.get(outcome, 0) + 1

    if len(candidates) < cap:
        _page_past_held_examples(
            source,
            candidates,
            rejections,
            held_fingerprints,
            cap=cap,
            domain_gaps=domain_gaps,
            outcomes=outcomes,
            seen=seen,
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
    domains: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Plan bounded reserve work from live KG evidence-coverage gaps.

    ``domains`` (``None`` = all supported) limits which evidence domains are
    planned; see :func:`evidence_gap_candidates`.
    """
    engine = engine or KnowledgeGapDiscoveryEngine(kg_source=source)
    queue = engine.research_queue(limit=RESEARCH_QUEUE_SCAN)
    held = frozenset(
        str(value) for value in snapshot.get("dispatch_fingerprints") or [] if value
    )
    candidates, rejections, unavailable = evidence_gap_candidates(
        queue, source, cap=cap, held_fingerprints=held, domains=domains
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
            "source_domains": sorted(domains) if domains is not None else None,
        }
    )
    return result
