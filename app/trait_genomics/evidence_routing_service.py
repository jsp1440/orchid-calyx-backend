from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .adaptive_retrieval import AdaptiveEuropePMCClient
from .evidence_router import ScientificEvidenceRouter
from .molecular_harvester import EuropePMCMolecularHarvester, MolecularHarvestTarget


ROUTING_DDL = """
CREATE SCHEMA IF NOT EXISTS oc_literature;
CREATE TABLE IF NOT EXISTS oc_literature.evidence_route_candidates (
    route_id text PRIMARY KEY,
    canonical_taxon_id text NOT NULL,
    scientific_name text NOT NULL,
    source_id text NOT NULL,
    source_uri text,
    title text,
    route text NOT NULL,
    confidence_score double precision NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 1),
    reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    pmid text,
    pmcid text,
    doi text,
    retrieval_strategy text,
    retrieval_query text,
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    review_state text NOT NULL DEFAULT 'candidate' CHECK (review_state IN ('candidate','accepted','rejected','needs_review')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (canonical_taxon_id, source_id, route)
);
CREATE INDEX IF NOT EXISTS idx_tig_evidence_route_taxon
    ON oc_literature.evidence_route_candidates (canonical_taxon_id, route);
CREATE INDEX IF NOT EXISTS idx_tig_evidence_route_review
    ON oc_literature.evidence_route_candidates (review_state, route);
"""


class RouteSink(Protocol):
    def upsert(self, row: dict[str, Any]) -> dict[str, Any]: ...


class LiteratureEvidenceRouteRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for literature evidence routing persistence")
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def ensure_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(ROUTING_DDL)
            conn.commit()

    def upsert(self, row: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        values = dict(row)
        values["reasons"] = Jsonb(list(row.get("reasons") or []))
        values["provenance"] = Jsonb(dict(row.get("provenance") or {}))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_literature.evidence_route_candidates (
                    route_id, canonical_taxon_id, scientific_name, source_id, source_uri,
                    title, route, confidence_score, reasons, pmid, pmcid, doi,
                    retrieval_strategy, retrieval_query, provenance
                ) VALUES (
                    %(route_id)s, %(canonical_taxon_id)s, %(scientific_name)s, %(source_id)s,
                    %(source_uri)s, %(title)s, %(route)s, %(confidence_score)s, %(reasons)s,
                    %(pmid)s, %(pmcid)s, %(doi)s, %(retrieval_strategy)s,
                    %(retrieval_query)s, %(provenance)s
                )
                ON CONFLICT (route_id) DO UPDATE SET
                    scientific_name=EXCLUDED.scientific_name,
                    source_uri=EXCLUDED.source_uri,
                    title=EXCLUDED.title,
                    route=EXCLUDED.route,
                    confidence_score=EXCLUDED.confidence_score,
                    reasons=EXCLUDED.reasons,
                    pmid=EXCLUDED.pmid,
                    pmcid=EXCLUDED.pmcid,
                    doi=EXCLUDED.doi,
                    retrieval_strategy=EXCLUDED.retrieval_strategy,
                    retrieval_query=EXCLUDED.retrieval_query,
                    provenance=EXCLUDED.provenance,
                    updated_at=now()
                RETURNING *
                """,
                values,
            )
            stored = cur.fetchone()
            conn.commit()
        return dict(stored)


@dataclass(frozen=True)
class RoutingDiagnostics:
    targets: int
    publications: int
    annotated_publications: int
    routed: int
    persisted: int
    molecular_association_candidate: int
    phylogenetic_sequence_context: int
    trait_morphology_evidence: int
    pollinator_selection_context: int
    pollination_ecology_evidence: int
    genomic_resource: int
    molecular_context: int
    general_orchid_literature: int


class LiteratureEvidenceRoutingService:
    """Route retrieved orchid literature to review-only scientific evidence channels."""

    def __init__(
        self,
        *,
        client: AdaptiveEuropePMCClient | Any | None = None,
        router: ScientificEvidenceRouter | None = None,
        repository: RouteSink | None = None,
    ) -> None:
        self.client = client or AdaptiveEuropePMCClient()
        self.router = router or ScientificEvidenceRouter()
        self.repository = repository or LiteratureEvidenceRouteRepository()
        self._molecular_gate = EuropePMCMolecularHarvester(client=self.client)

    @staticmethod
    def _source_identity(article: dict[str, Any]) -> tuple[str, str | None, str | None, str | None, str | None]:
        pmid = str(article.get("pmid") or "").strip() or None
        pmcid = str(article.get("pmcid") or "").strip() or None
        doi = str(article.get("doi") or "").strip() or None
        if pmid:
            return f"pmid:{pmid}", f"https://europepmc.org/article/MED/{pmid}", pmid, pmcid, doi
        if pmcid:
            return f"pmcid:{pmcid}", f"https://europepmc.org/article/PMC/{pmcid}", None, pmcid, doi
        if doi:
            return f"doi:{doi}", f"https://europepmc.org/article/DOI/{doi}", None, None, doi
        ext = str(article.get("id") or article.get("extId") or "unknown").strip()
        return f"europepmc:{ext}", None, None, None, None

    @staticmethod
    def _route_id(canonical_taxon_id: str, source_id: str, route: str) -> str:
        payload = f"{canonical_taxon_id}|{source_id}|{route}".encode()
        return f"tig-route:{hashlib.sha256(payload).hexdigest()[:24]}"

    def _strict_candidate_count(
        self,
        target: MolecularHarvestTarget,
        article: dict[str, Any],
        annotations: list[dict[str, Any]],
    ) -> int:
        abstract = str(article.get("abstractText") or "").strip()
        if not abstract or not annotations:
            return 0
        produced = 0
        for annotation in annotations:
            candidate = self._molecular_gate._candidate_from_text(
                target=target,
                article=article,
                annotation=annotation,
                text=abstract,
                evidence_scope="abstract",
                evidence_section="Abstract",
            )
            if candidate is not None:
                produced += 1
        return produced

    def route(
        self,
        targets: list[MolecularHarvestTarget],
        *,
        page_size: int = 25,
        persist: bool = False,
    ) -> dict[str, Any]:
        if page_size < 1 or page_size > 100:
            raise ValueError("page_size must be between 1 and 100")

        routed_rows: list[dict[str, Any]] = []
        persisted_rows: list[dict[str, Any]] = []
        annotated_publications = 0
        route_counts: dict[str, int] = {
            "molecular_association_candidate": 0,
            "phylogenetic_sequence_context": 0,
            "trait_morphology_evidence": 0,
            "pollinator_selection_context": 0,
            "pollination_ecology_evidence": 0,
            "genomic_resource": 0,
            "molecular_context": 0,
            "general_orchid_literature": 0,
        }
        publications = 0

        for target in targets:
            articles = self.client.search(target.scientific_name, page_size=page_size)
            publications += len(articles)
            for article in articles:
                article_id = EuropePMCMolecularHarvester._article_id(article)
                annotations = self.client.annotations(article_id) if article_id else []
                if annotations:
                    annotated_publications += 1
                strict_count = self._strict_candidate_count(target, article, annotations)
                classification = self.router.route(
                    article,
                    has_gene_annotations=bool(annotations),
                    molecular_candidate_count=strict_count,
                    full_text_available=str(article.get("isOpenAccess") or "").casefold() == "y",
                )
                route_counts[classification.route] = route_counts.get(classification.route, 0) + 1
                source_id, source_uri, pmid, pmcid, doi = self._source_identity(article)
                row = {
                    "route_id": self._route_id(target.canonical_taxon_id, source_id, classification.route),
                    "canonical_taxon_id": target.canonical_taxon_id,
                    "scientific_name": target.scientific_name,
                    "source_id": source_id,
                    "source_uri": source_uri,
                    "title": str(article.get("title") or "").strip() or None,
                    "route": classification.route,
                    "confidence_score": classification.confidence,
                    "reasons": list(classification.reasons),
                    "pmid": pmid,
                    "pmcid": pmcid,
                    "doi": doi,
                    "retrieval_strategy": article.get("_calyx_retrieval_strategy"),
                    "retrieval_query": article.get("_calyx_retrieval_query"),
                    "provenance": {
                        "provider": "Europe PMC",
                        "routing_policy": "descriptive_review_only_not_live_tig_evidence",
                        "gene_annotation_count": len(annotations),
                        "strict_molecular_candidate_count": strict_count,
                        "open_access": article.get("isOpenAccess"),
                    },
                }
                routed_rows.append(row)
                if persist:
                    persisted_rows.append(self.repository.upsert(row))

        diagnostics = RoutingDiagnostics(
            targets=len(targets),
            publications=publications,
            annotated_publications=annotated_publications,
            routed=len(routed_rows),
            persisted=len(persisted_rows),
            **route_counts,
        )
        result = {
            "diagnostics": diagnostics.__dict__,
            "routes": routed_rows,
            "persisted": persist,
            "live_tig_eligible": False,
            "review_required": True,
            "policy": (
                "Routing preserves useful literature in evidence-specific review channels. "
                "A route is descriptive only and never upgrades a paper to accepted molecular "
                "association evidence or a causal claim."
            ),
        }
        if hasattr(self.client, "retrieval_diagnostics"):
            result["retrieval_diagnostics"] = self.client.retrieval_diagnostics()
        return result