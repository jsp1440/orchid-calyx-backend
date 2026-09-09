"""Canonical cross-domain relationship integration for audit remediation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

#: Statuses under which a link still asserts something about the Continuum.
STANDING_STATUSES = frozenset({"provisional", "verified"})
#: Statuses under which a link asserts nothing, having been withdrawn.
WITHDRAWN_STATUSES = frozenset({"rejected", "superseded"})

AUDIT_TARGET_DOMAINS = (
    "images",
    "occurrences",
    "elevation",
    "climate",
    "literature",
    "pollinators",
    "mycorrhiza",
    "habitat",
    "conservation",
)


@dataclass(frozen=True)
class RelationshipLink:
    source_domain: str
    source_record_id: str
    target_domain: str
    target_record_id: str
    relationship_type: str
    taxon_id: str | None
    match_method: str
    confidence: float = 1.0
    provenance: dict[str, Any] | None = None
    validation_status: str = "provisional"

    def validated(self) -> RelationshipLink:
        if not self.source_domain or not self.target_domain:
            raise ValueError("source_domain and target_domain are required")
        if not self.source_record_id or not self.target_record_id:
            raise ValueError("source_record_id and target_record_id are required")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.validation_status not in {
            "provisional",
            "verified",
            "rejected",
            "superseded",
        }:
            raise ValueError("unsupported validation_status")
        if self.source_domain == "taxonomy" and not self.taxon_id:
            raise ValueError("taxonomy links require taxon_id")
        return self

    def as_record(self) -> dict[str, Any]:
        self.validated()
        payload = asdict(self)
        payload["provenance"] = self.provenance or {}
        return payload


class RelationshipIntegrationAudit:
    """Summarize audit coverage and graph-integrity problems."""

    def __init__(self, links: Iterable[RelationshipLink]) -> None:
        self._links = tuple(link.validated() for link in links)

    def coverage(self) -> dict[str, dict[str, int | bool | str]]:
        """Coverage a domain actually has, counting only links that still stand.

        A rejected or superseded link is not coverage. It is a relationship
        somebody asserted and the record then withdrew, and counting it reports
        knowledge the Continuum does not hold — the exact failure this audit
        exists to detect, occurring inside the audit itself.

        Withdrawn links are still counted and reported, under their own keys.
        Dropping them would replace one false statement with another: that
        nobody ever asserted the relationship. "Never asserted" and "asserted
        and withdrawn" are different findings, and a reader deciding where to
        direct curation needs to tell them apart.
        """
        result: dict[str, dict[str, int | bool | str]] = {}
        for domain in AUDIT_TARGET_DOMAINS:
            domain_links = [
                link
                for link in self._links
                if link.source_domain == "taxonomy" and link.target_domain == domain
            ]
            standing = [
                link
                for link in domain_links
                if link.validation_status in STANDING_STATUSES
            ]
            withdrawn = [
                link
                for link in domain_links
                if link.validation_status in WITHDRAWN_STATUSES
            ]
            result[f"taxonomy_to_{domain}"] = {
                "present": bool(standing),
                "link_count": len(standing),
                "linked_taxa": len({link.taxon_id for link in standing}),
                "verified_links": sum(
                    link.validation_status == "verified" for link in standing
                ),
                "withdrawn_link_count": len(withdrawn),
                # Distinguishes a domain nobody has worked on from one whose
                # every assertion was thrown out. Both have no coverage; they
                # call for opposite next actions.
                "coverage_state": (
                    "present"
                    if standing
                    else "withdrawn"
                    if withdrawn
                    else "never_asserted"
                ),
            }
        return result

    def integrity_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, str, str]] = set()
        for link in self._links:
            key = (
                link.source_domain,
                link.source_record_id,
                link.target_domain,
                link.target_record_id,
                link.relationship_type,
            )
            if key in seen:
                issues.append({"issue": "duplicate_edge", "link": link.as_record()})
            seen.add(key)
            if (
                link.source_domain == link.target_domain
                and link.source_record_id == link.target_record_id
            ):
                issues.append({"issue": "self_loop", "link": link.as_record()})
            if not link.provenance:
                issues.append({"issue": "missing_provenance", "link": link.as_record()})
        return issues

    def report(self) -> dict[str, Any]:
        coverage = self.coverage()
        integrity = self.integrity_issues()
        return {
            "coverage": coverage,
            "missing_relationships": [
                name for name, status in coverage.items() if not status["present"]
            ],
            "knowledge_graph_node_edge_integrity": {
                "passed": not integrity,
                "issue_count": len(integrity),
                "issues": integrity,
            },
        }
