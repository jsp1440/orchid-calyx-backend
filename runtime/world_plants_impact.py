"""Read-only downstream impact analysis for proposed taxonomy crosswalks."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from runtime.world_plants_delta import CrosswalkCandidate

DOMAINS = (
    "images",
    "occurrences",
    "literature",
    "traits",
    "pollinators",
    "mycorrhizae",
    "conservation",
    "species_profiles",
    "knowledge_graph_edges",
)


@dataclass(frozen=True)
class TaxonImpact:
    previous_row: int
    classification: str
    domain_counts: dict[str, int]
    total_records: int
    risk_level: str
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["blockers"] = list(self.blockers)
        return result


@dataclass(frozen=True)
class ImpactAudit:
    taxa: tuple[TaxonImpact, ...]
    domain_totals: dict[str, int]
    risk_totals: dict[str, int]
    promotion_blocked: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "taxa": [item.as_dict() for item in self.taxa],
            "domain_totals": dict(self.domain_totals),
            "risk_totals": dict(self.risk_totals),
            "promotion_blocked": self.promotion_blocked,
            "read_only": True,
        }


def _risk(candidate: CrosswalkCandidate, total: int) -> tuple[str, tuple[str, ...]]:
    blockers: list[str] = []
    if candidate.classification in {"ambiguous", "removed"}:
        blockers.append(f"unresolved_{candidate.classification}_mapping")
    if total >= 100000:
        blockers.append("very_large_downstream_fanout")
        return "critical", tuple(blockers)
    if total >= 10000 or blockers:
        return "high", tuple(blockers)
    if total >= 1000 or candidate.classification not in {
        "unchanged",
        "authorship_or_format_change",
    }:
        return "medium", tuple(blockers)
    return "low", tuple(blockers)


def audit_downstream_impact(
    candidates: Iterable[CrosswalkCandidate],
    counts_by_previous_row: Mapping[int, Mapping[str, int]],
) -> ImpactAudit:
    """Aggregate precomputed read-only domain counts for each crosswalk candidate."""

    impacts: list[TaxonImpact] = []
    domain_totals: dict[str, int] = defaultdict(int)
    risk_totals: dict[str, int] = defaultdict(int)
    promotion_blocked = False

    for candidate in candidates:
        supplied = counts_by_previous_row.get(candidate.previous_row, {})
        domain_counts = {
            domain: max(0, int(supplied.get(domain, 0))) for domain in DOMAINS
        }
        total = sum(domain_counts.values())
        risk_level, blockers = _risk(candidate, total)
        if blockers:
            promotion_blocked = True
        for domain, count in domain_counts.items():
            domain_totals[domain] += count
        risk_totals[risk_level] += 1
        impacts.append(
            TaxonImpact(
                previous_row=candidate.previous_row,
                classification=candidate.classification,
                domain_counts=domain_counts,
                total_records=total,
                risk_level=risk_level,
                blockers=blockers,
            )
        )

    return ImpactAudit(
        taxa=tuple(impacts),
        domain_totals=dict(domain_totals),
        risk_totals=dict(risk_totals),
        promotion_blocked=promotion_blocked,
    )


def read_only_query_contract() -> dict[str, str]:
    """Document the required result contract for database adapters."""
    return {
        "key": "previous_source_row_number",
        **{domain: "non-negative integer count" for domain in DOMAINS},
        "mutation_policy": "SELECT-only; no INSERT, UPDATE, DELETE, or DDL",
    }
