"""Evidence-coverage knowledge gaps, counted from the persisted knowledge graph.

This replaces keyword matching over discovery-memory module names as the gap
source for Brain's "knowledge-gap discovery -> research mission" step. Every
number here is a count of rows in ``oc_graph.kg_nodes`` / ``kg_edges``:

* taxa examined: active ``taxon`` nodes;
* taxa covering a dossier evidence domain: taxa with at least one active
  ``supported_by_evidence`` edge to an active ``evidence`` node whose
  ``payload_json->>'evidence_type'`` belongs to that domain, or with an active
  edge of the domain's own relation type (for example ``documented_by``);
* partial federated coverage: taxa that a federated source already holds
  evidence for, lacking a domain that the same source supplies for other taxa.
  These are the cheapest to complete, so they rank first.

Read-only: every statement is a SELECT inside a READ ONLY transaction. Nothing
here reads or emits excerpt text, so locality prose never leaves the database.
Any evidence a resulting research mission finds enters as provisional/candidate
evidence through the controlled KG publication workflow; nothing is published.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.species_dossier.repository import (
    FEDERATED_SECTION_TYPES,
    WITHHELD_EVIDENCE_TYPES,
    YONG_GEE_SOURCE_NAME,
    YONG_GEE_SOURCE_TABLE,
)

EVIDENCE_COVERAGE_METHOD = (
    "evidence coverage counted from oc_graph.kg_nodes/kg_edges: active taxon nodes "
    "with active supported_by_evidence edges to evidence nodes by payload evidence_type, "
    "or with the domain's own relation edges; read-only"
)
KG_SOURCE_ID = "oc_graph.kg_nodes/kg_edges"
MAX_EXAMPLE_TAXA = 5
STATEMENT_TIMEOUT = "20s"
EVIDENCE_ENTRY_STATE = (
    "Any evidence found enters as provisional/candidate evidence through the "
    "controlled Knowledge Graph publication workflow with human review; this "
    "mission publishes nothing."
)
KNOWN_SOURCE_NAMES = {YONG_GEE_SOURCE_TABLE: YONG_GEE_SOURCE_NAME}

DbExecute = Callable[[Callable[[Any], Any]], Any]


@dataclass(frozen=True)
class EvidenceDomain:
    name: str
    #: Species-page order: domains the dossier already renders from evidence
    #: first, then domains it cannot show yet; locality-gated domains form their
    #: own trailing tier (see :func:`severity_for`).
    rank: int
    evidence_types: tuple[str, ...] = ()
    relation_edge_types: tuple[str, ...] = ()
    dossier_renders_evidence: bool = False
    locality_gated: bool = False


EVIDENCE_DOMAINS: tuple[EvidenceDomain, ...] = (
    EvidenceDomain(
        "nomenclature",
        0,
        FEDERATED_SECTION_TYPES["nomenclature"],
        dossier_renders_evidence=True,
    ),
    EvidenceDomain(
        "morphology",
        1,
        FEDERATED_SECTION_TYPES["morphology"],
        dossier_renders_evidence=True,
    ),
    EvidenceDomain(
        "phenology",
        2,
        FEDERATED_SECTION_TYPES["phenology"],
        dossier_renders_evidence=True,
    ),
    EvidenceDomain(
        "literature",
        3,
        FEDERATED_SECTION_TYPES["literature"],
        ("documented_by",),
        dossier_renders_evidence=True,
    ),
    EvidenceDomain("conservation", 4, (), ("has_conservation_assessment",)),
    EvidenceDomain("pollinators", 5, (), ("associated_with_pollinator",)),
    EvidenceDomain("mycorrhizae", 6, (), ("associated_with_mycorrhiza",)),
    EvidenceDomain(
        "distribution",
        0,
        WITHHELD_EVIDENCE_TYPES,
        ("occurs_in", "occupies_habitat"),
        locality_gated=True,
    ),
)
#: Tiers, in order: partial federated coverage (cheapest to complete), then no
#: coverage; locality-gated domains after every other domain.
_TIER_BASE = {
    (False, True): 100,
    (False, False): 70,
    (True, True): 20,
    (True, False): 10,
}


class EvidenceCoverageUnavailable(RuntimeError):
    """The KG cannot be read; callers fail closed to the stored record."""


@dataclass
class EvidenceCoverageGap:
    gap_id: str
    domain: str
    title: str
    priority: str
    severity_score: int
    evidence: list[str] = field(default_factory=list)
    proposed_action: str = ""
    source: str = "evidence_coverage_kg"
    method: str = EVIDENCE_COVERAGE_METHOD
    counts: dict[str, int] = field(default_factory=dict)
    example_taxon_ids: list[str] = field(default_factory=list)
    candidate_source: dict[str, Any] | None = None
    locality_gated: bool = False
    dossier_renders_evidence: bool = False
    evidence_entry_state: str = EVIDENCE_ENTRY_STATE


def severity_for(domain: EvidenceDomain, *, partial: bool) -> int:
    """Deterministic rank score: tier first, then species-page order within it."""
    return _TIER_BASE[(domain.locality_gated, partial)] - 4 * domain.rank


def priority_for(domain: EvidenceDomain, *, partial: bool) -> str:
    if domain.locality_gated:
        return "LOW"
    if partial:
        return "CRITICAL" if domain.dossier_renders_evidence else "HIGH"
    return "HIGH" if domain.dossier_renders_evidence else "MEDIUM"


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value.upper()).strip("-")


# -- SQL (every statement read-only) --------------------------------------------------------

_TAXON = "t.node_type = 'taxon' AND t.is_active IS TRUE"
_COVERED_TAXA = f"""
    SELECT DISTINCT t.kg_node_id
    FROM oc_graph.kg_nodes t
    JOIN oc_graph.kg_edges e ON e.from_node_id = t.kg_node_id AND e.is_active IS TRUE
    JOIN oc_graph.kg_nodes n ON n.kg_node_id = e.to_node_id AND n.is_active IS TRUE
    WHERE {_TAXON}
      AND ((e.edge_type = 'supported_by_evidence' AND n.node_type = 'evidence'
            AND COALESCE(n.payload_json->>'evidence_type', '') = ANY(%s::text[]))
           OR e.edge_type = ANY(%s::text[]))
"""
_SOURCE_TAXA = f"""
    SELECT DISTINCT t.kg_node_id, t.source_pk
    FROM oc_graph.kg_nodes t
    JOIN oc_graph.kg_edges e ON e.from_node_id = t.kg_node_id AND e.is_active IS TRUE
    JOIN oc_graph.kg_nodes n ON n.kg_node_id = e.to_node_id AND n.is_active IS TRUE
    WHERE {_TAXON}
      AND e.edge_type = 'supported_by_evidence' AND n.node_type = 'evidence'
      AND n.source_table = %s
"""
SQL_PRESENT = (
    "SELECT to_regclass('oc_graph.kg_nodes') IS NOT NULL AS nodes_present, "
    "to_regclass('oc_graph.kg_edges') IS NOT NULL AS edges_present"
)
SQL_TAXA_EXAMINED = f"SELECT COUNT(*) AS n FROM oc_graph.kg_nodes t WHERE {_TAXON}"
SQL_DOMAIN_COVERED = f"SELECT COUNT(*) AS n FROM ({_COVERED_TAXA}) covered"
SQL_DOMAIN_EXAMPLES = f"""
    SELECT t.source_pk FROM oc_graph.kg_nodes t
    WHERE {_TAXON} AND t.kg_node_id NOT IN ({_COVERED_TAXA})
    ORDER BY t.source_pk LIMIT %s
"""
SQL_EVIDENCE_SOURCES = f"""
    SELECT n.source_table, COUNT(DISTINCT t.kg_node_id) AS taxa
    FROM oc_graph.kg_nodes t
    JOIN oc_graph.kg_edges e ON e.from_node_id = t.kg_node_id AND e.is_active IS TRUE
    JOIN oc_graph.kg_nodes n ON n.kg_node_id = e.to_node_id AND n.is_active IS TRUE
    WHERE {_TAXON}
      AND e.edge_type = 'supported_by_evidence' AND n.node_type = 'evidence'
      AND n.source_table IS NOT NULL
    GROUP BY n.source_table
    ORDER BY n.source_table
"""
SQL_SOURCE_DOMAIN_TAXA = f"""
    SELECT COUNT(DISTINCT t.kg_node_id) AS n
    FROM oc_graph.kg_nodes t
    JOIN oc_graph.kg_edges e ON e.from_node_id = t.kg_node_id AND e.is_active IS TRUE
    JOIN oc_graph.kg_nodes n ON n.kg_node_id = e.to_node_id AND n.is_active IS TRUE
    WHERE {_TAXON}
      AND e.edge_type = 'supported_by_evidence' AND n.node_type = 'evidence'
      AND n.source_table = %s
      AND COALESCE(n.payload_json->>'evidence_type', '') = ANY(%s::text[])
"""
SQL_TAXON_LABELS = f"""
    SELECT t.source_pk, t.display_label FROM oc_graph.kg_nodes t
    WHERE {_TAXON} AND t.source_pk = ANY(%s::text[])
    ORDER BY t.source_pk
"""
SQL_PARTIAL_COUNT = f"""
    SELECT COUNT(*) AS n FROM ({_SOURCE_TAXA}) src
    WHERE src.kg_node_id NOT IN ({_COVERED_TAXA})
"""
SQL_PARTIAL_EXAMPLES = f"""
    SELECT src.source_pk FROM ({_SOURCE_TAXA}) src
    WHERE src.kg_node_id NOT IN ({_COVERED_TAXA})
    ORDER BY src.source_pk LIMIT %s
"""


def _count(cur: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    return int(row["n"]) if row and row.get("n") is not None else 0


def _ids(cur: Any, sql: str, params: tuple[Any, ...]) -> list[str]:
    cur.execute(sql, params)
    return [
        str(row["source_pk"])
        for row in cur.fetchall()
        if row.get("source_pk") is not None
    ]


class EvidenceCoverageGapSource:
    """Counts dossier evidence-domain coverage per taxon from the KG (read-only)."""

    method = EVIDENCE_COVERAGE_METHOD

    def __init__(
        self, db_execute: DbExecute | None, *, unavailable_reason: str | None = None
    ) -> None:
        self._db_execute = db_execute
        self._unavailable_reason = unavailable_reason

    def collect(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Return a gap payload, or raise :class:`EvidenceCoverageUnavailable`."""
        if self._db_execute is None:
            raise EvidenceCoverageUnavailable(
                self._unavailable_reason
                or "no knowledge-graph connection is configured"
            )
        now = now or datetime.now(timezone.utc)
        try:
            result = self._db_execute(self._work)
        except EvidenceCoverageUnavailable:
            raise
        except Exception as exc:  # the KG could not be read: fail closed
            raise EvidenceCoverageUnavailable(
                f"knowledge-graph read failed: {type(exc).__name__}"
            ) from exc
        if result is None:
            raise EvidenceCoverageUnavailable(
                "no knowledge-graph connection is configured"
            )
        coverage, gaps, taxa_examined, sources = result
        generated_at = now.isoformat()
        return {
            "generated_at": generated_at,
            "method": EVIDENCE_COVERAGE_METHOD,
            "source_id": KG_SOURCE_ID,
            "summary": {
                "domains": len(coverage),
                "gaps": len(gaps),
                "critical": sum(1 for gap in gaps if gap.priority == "CRITICAL"),
                "high": sum(1 for gap in gaps if gap.priority == "HIGH"),
                "taxa_examined": taxa_examined,
                "evidence_sources": len(sources),
            },
            "domain_coverage": coverage,
            "evidence_sources": sources,
            "gaps": [asdict(gap) for gap in gaps],
            "top_actions": [gap.proposed_action for gap in gaps[:5]],
        }

    def taxon_labels(self, taxon_ids: list[str]) -> dict[str, str]:
        """Display labels of active KG taxon nodes, by ``source_pk`` (read-only).

        Ids with no active node or an empty label are absent: a name is never
        invented. Raises :class:`EvidenceCoverageUnavailable` if the KG cannot be read.
        """
        wanted = sorted({str(value) for value in taxon_ids if str(value).strip()})
        if not wanted:
            return {}
        if self._db_execute is None:
            raise EvidenceCoverageUnavailable(
                self._unavailable_reason
                or "no knowledge-graph connection is configured"
            )

        def _work(cur: Any) -> dict[str, str] | None:
            if cur is None:
                return None
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute(SQL_TAXON_LABELS, (wanted,))
            labels: dict[str, str] = {}
            for row in cur.fetchall():
                label = " ".join(str(row.get("display_label") or "").split())
                if label and row.get("source_pk") is not None:
                    labels[str(row["source_pk"])] = label
            return labels

        try:
            result = self._db_execute(_work)
        except Exception as exc:
            raise EvidenceCoverageUnavailable(
                f"knowledge-graph read failed: {type(exc).__name__}"
            ) from exc
        if result is None:
            raise EvidenceCoverageUnavailable(
                "no knowledge-graph connection is configured"
            )
        return result

    # -- internals --------------------------------------------------------------------------

    def _work(
        self, cur: Any
    ) -> (
        tuple[
            dict[str, dict[str, Any]],
            list[EvidenceCoverageGap],
            int,
            list[dict[str, Any]],
        ]
        | None
    ):
        if cur is None:
            return None
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
        cur.execute(SQL_PRESENT)
        present = cur.fetchone()
        if not present or not present["nodes_present"] or not present["edges_present"]:
            raise EvidenceCoverageUnavailable(
                "the persisted knowledge graph is not provisioned in this database"
            )
        taxa_examined = _count(cur, SQL_TAXA_EXAMINED)
        if taxa_examined == 0:
            raise EvidenceCoverageUnavailable(
                "the knowledge graph holds no active taxon nodes; coverage cannot be assessed"
            )
        cur.execute(SQL_EVIDENCE_SOURCES)
        sources = [
            {
                "source_table": str(row["source_table"]),
                "source_name": KNOWN_SOURCE_NAMES.get(
                    str(row["source_table"]), str(row["source_table"])
                ),
                "taxa_with_evidence": int(row["taxa"]),
            }
            for row in cur.fetchall()
        ]

        coverage: dict[str, dict[str, Any]] = {}
        gaps: list[EvidenceCoverageGap] = []
        for domain in EVIDENCE_DOMAINS:
            types = list(domain.evidence_types)
            relations = list(domain.relation_edge_types)
            covered = _count(cur, SQL_DOMAIN_COVERED, (types, relations))
            lacking = max(taxa_examined - covered, 0)
            examples = (
                _ids(cur, SQL_DOMAIN_EXAMPLES, (types, relations, MAX_EXAMPLE_TAXA))
                if lacking
                else []
            )
            partial: list[dict[str, Any]] = []
            for source in sources:
                if not types:
                    continue
                supplied = _count(
                    cur, SQL_SOURCE_DOMAIN_TAXA, (source["source_table"], types)
                )
                if not supplied:
                    continue  # this source does not supply this domain at all
                params = (source["source_table"], types, relations)
                missing = _count(cur, SQL_PARTIAL_COUNT, params)
                if not missing:
                    continue
                partial.append(
                    {
                        **source,
                        "taxa_supplied_in_domain": supplied,
                        "taxa_held_lacking_domain": missing,
                        "example_taxon_ids": _ids(
                            cur, SQL_PARTIAL_EXAMPLES, (*params, MAX_EXAMPLE_TAXA)
                        ),
                    }
                )
            coverage[domain.name] = {
                "taxa_examined": taxa_examined,
                "taxa_covered": covered,
                "taxa_lacking": lacking,
                "evidence_types": types,
                "relation_edge_types": relations,
                "status": "covered"
                if not lacking
                else "gap"
                if not covered
                else "partial",
                "partial_federated_coverage": partial,
                "locality_gated": domain.locality_gated,
                "dossier_renders_evidence": domain.dossier_renders_evidence,
                "method": EVIDENCE_COVERAGE_METHOD,
            }
            gaps.extend(
                self._gaps_for(domain, coverage[domain.name], examples, partial)
            )
        gaps.sort(key=lambda gap: (-gap.severity_score, gap.gap_id))
        return coverage, gaps, taxa_examined, sources

    @staticmethod
    def _gaps_for(
        domain: EvidenceDomain,
        info: dict[str, Any],
        examples: list[str],
        partial: list[dict[str, Any]],
    ) -> list[EvidenceCoverageGap]:
        gaps: list[EvidenceCoverageGap] = []
        gate = (
            " Locality-gated: evidence must pass locality-sensitivity review before any "
            "exposure; the species dossier withholds it."
            if domain.locality_gated
            else ""
        )
        for source in partial:
            severity = severity_for(domain, partial=True)
            missing = source["taxa_held_lacking_domain"]
            gaps.append(
                EvidenceCoverageGap(
                    gap_id=f"KG-EVCOV-{_slug(domain.name)}-{_slug(source['source_table'])}",
                    domain=domain.name,
                    title=(
                        f"{missing} taxa held by {source['source_name']} lack "
                        f"{domain.name} evidence"
                    ),
                    priority=priority_for(domain, partial=True),
                    severity_score=severity,
                    evidence=[
                        f"taxa_examined={info['taxa_examined']}",
                        f"taxa_held_by_source={source['taxa_with_evidence']}",
                        f"taxa_supplied_in_domain_by_source={source['taxa_supplied_in_domain']}",
                        f"taxa_held_lacking_domain={missing}",
                        f"Method: {EVIDENCE_COVERAGE_METHOD}",
                    ],
                    proposed_action=(
                        f"For the {missing} taxa already reconciled to {source['source_name']} "
                        f"but lacking {domain.name} evidence, check the source's current record "
                        f"and its underlying citations for {', '.join(domain.evidence_types)}."
                        f"{gate} {EVIDENCE_ENTRY_STATE}"
                    ),
                    counts={
                        "taxa_examined": info["taxa_examined"],
                        "taxa_held_by_source": source["taxa_with_evidence"],
                        "taxa_supplied_in_domain_by_source": source[
                            "taxa_supplied_in_domain"
                        ],
                        "taxa_held_lacking_domain": missing,
                    },
                    example_taxon_ids=list(source["example_taxon_ids"]),
                    candidate_source={
                        "source_table": source["source_table"],
                        "source_name": source["source_name"],
                        "coverage": "partial",
                    },
                    locality_gated=domain.locality_gated,
                    dossier_renders_evidence=domain.dossier_renders_evidence,
                )
            )
        if info["taxa_lacking"]:
            severity = severity_for(domain, partial=False)
            wanted = ", ".join(
                [
                    *domain.evidence_types,
                    *(f"{e} edges" for e in domain.relation_edge_types),
                ]
            )
            gaps.append(
                EvidenceCoverageGap(
                    gap_id=f"KG-EVCOV-{_slug(domain.name)}",
                    domain=domain.name,
                    title=(
                        f"{info['taxa_lacking']} of {info['taxa_examined']} taxa lack "
                        f"{domain.name} evidence"
                    ),
                    priority=priority_for(domain, partial=False),
                    severity_score=severity,
                    evidence=[
                        f"taxa_examined={info['taxa_examined']}",
                        f"taxa_covered={info['taxa_covered']}",
                        f"taxa_lacking={info['taxa_lacking']}",
                        f"Method: {EVIDENCE_COVERAGE_METHOD}",
                    ],
                    proposed_action=(
                        f"Identify a licensed source for {domain.name} evidence ({wanted}) "
                        f"for the {info['taxa_lacking']} taxa without it; no federated source in "
                        f"the KG covers them yet.{gate} {EVIDENCE_ENTRY_STATE}"
                    ),
                    counts={
                        "taxa_examined": info["taxa_examined"],
                        "taxa_covered": info["taxa_covered"],
                        "taxa_lacking": info["taxa_lacking"],
                    },
                    example_taxon_ids=examples,
                    candidate_source=None,
                    locality_gated=domain.locality_gated,
                    dossier_renders_evidence=domain.dossier_renders_evidence,
                )
            )
        return gaps


def research_mission(gap: dict[str, Any]) -> dict[str, Any]:
    """The actionable mission for one evidence-coverage gap."""
    candidate = gap.get("candidate_source")
    counts = gap.get("counts") or {}
    return {
        "domain": gap.get("domain"),
        "taxon_scope": {
            "taxa": counts.get("taxa_held_lacking_domain", counts.get("taxa_lacking")),
            "example_taxon_ids": list(gap.get("example_taxon_ids") or []),
        },
        "missing": f"{gap.get('domain')} evidence (no supported_by_evidence or relation edge)",
        "candidate_source": candidate,
        "locality_gated": bool(gap.get("locality_gated")),
        "evidence_entry_state": gap.get("evidence_entry_state") or EVIDENCE_ENTRY_STATE,
        "publishes": False,
    }
