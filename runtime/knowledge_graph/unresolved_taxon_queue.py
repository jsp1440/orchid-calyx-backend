"""Build a review queue for graph source records that cannot be linked safely.

The queue is descriptive and read-only. It converts projection blockers and
unresolved source rows into explicit operator work rather than silently dropping
records or guessing taxonomic identity.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from .dynamic_source_projection import ProjectionPlan


@dataclass(frozen=True)
class UnresolvedTaxonItem:
    domain: str
    source: str | None
    reason: str
    review_state: str = "needs_taxon_resolution"
    suggested_action: str = "create_or_verify_canonical_crosswalk"
    source_pk: str | None = None
    supplied_taxon_value: str | None = None
    supplied_scientific_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def queue_from_projection_plans(plans: Iterable[ProjectionPlan]) -> list[UnresolvedTaxonItem]:
    items: list[UnresolvedTaxonItem] = []
    for plan in plans:
        if plan.state not in {"blocked", "unavailable"}:
            continue
        items.append(
            UnresolvedTaxonItem(
                domain=plan.domain,
                source=plan.source,
                reason=plan.limitation or "Canonical taxon mapping is unavailable.",
                review_state="source_unavailable" if plan.state == "unavailable" else "needs_taxon_resolution",
                suggested_action=(
                    "locate_or_ingest_authoritative_source"
                    if plan.state == "unavailable"
                    else "create_or_verify_canonical_crosswalk"
                ),
            )
        )
    return items


def queue_from_rows(domain: str, source: str, rows: Iterable[dict[str, Any]]) -> list[UnresolvedTaxonItem]:
    """Convert unresolved source rows into bounded, reviewable queue items."""
    items: list[UnresolvedTaxonItem] = []
    for row in rows:
        items.append(
            UnresolvedTaxonItem(
                domain=domain,
                source=source,
                reason=str(row.get("reason") or "Canonical taxon could not be resolved safely."),
                source_pk=None if row.get("source_pk") is None else str(row.get("source_pk")),
                supplied_taxon_value=(
                    None if row.get("taxon_value") is None else str(row.get("taxon_value"))
                ),
                supplied_scientific_name=row.get("scientific_name"),
            )
        )
    return items


def unresolved_queue_report(items: Iterable[UnresolvedTaxonItem]) -> dict[str, Any]:
    queue = list(items)
    by_domain: dict[str, int] = {}
    for item in queue:
        by_domain[item.domain] = by_domain.get(item.domain, 0) + 1
    return {
        "contract": "calyx-unresolved-taxon-review-queue-v1",
        "count": len(queue),
        "by_domain": by_domain,
        "items": [item.to_dict() for item in queue[:500]],
        "truncated": len(queue) > 500,
        "publication_blocked": bool(queue),
    }
