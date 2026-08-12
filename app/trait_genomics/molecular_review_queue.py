from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from .molecular_evidence import MolecularEvidenceRepository

ReviewState = Literal["candidate", "accepted", "rejected", "needs_review"]
EvidenceKind = Literal[
    "genetic_association",
    "expression_association",
    "selection_association",
]


class MolecularReviewQueueQuery(BaseModel):
    review_state: ReviewState | None = None
    evidence_kind: EvidenceKind | None = None
    canonical_taxon_id: str | None = None
    scientific_name: str | None = None
    source_id: str | None = None
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


@dataclass(frozen=True)
class MolecularReviewQueuePage:
    total: int
    limit: int
    offset: int
    items: tuple[dict[str, Any], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "limit": self.limit,
            "offset": self.offset,
            "items": list(self.items),
            "review_required": True,
            "publication_enabled": False,
        }


def build_review_queue_filter(query: MolecularReviewQueueQuery) -> tuple[str, tuple[Any, ...]]:
    """Build a fixed-column parameterized WHERE clause for review queue reads."""

    clauses: list[str] = ["confidence_score >= %s"]
    params: list[Any] = [query.min_confidence]
    if query.review_state:
        clauses.append("review_state = %s")
        params.append(query.review_state)
    if query.evidence_kind:
        clauses.append("evidence_kind = %s")
        params.append(query.evidence_kind)
    if query.canonical_taxon_id:
        clauses.append("canonical_taxon_id = %s")
        params.append(query.canonical_taxon_id.strip())
    if query.scientific_name:
        clauses.append("scientific_name ILIKE %s")
        params.append(f"%{query.scientific_name.strip()}%")
    if query.source_id:
        clauses.append("source_id = %s")
        params.append(query.source_id.strip())
    return " AND ".join(clauses), tuple(params)


class MolecularReviewQueueRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for molecular review queue")
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def list(self, query: MolecularReviewQueueQuery) -> MolecularReviewQueuePage:
        MolecularEvidenceRepository(self.database_url).ensure_schema()
        where_sql, params = build_review_queue_filter(query)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT count(*) AS total
                FROM oc_genomics.molecular_evidence_candidates
                WHERE {where_sql}
                """,
                params,
            )
            total = int(cur.fetchone()["total"] or 0)
            cur.execute(
                f"""
                SELECT association_id, canonical_taxon_id, scientific_name,
                       evidence_kind, trait_predicate, trait_value, association_type,
                       gene_id, protein_id, sequence_accession, pathway_id, marker_name,
                       effect_value, evidence_text, method, source_id, source_uri,
                       doi, pmid, publication_id, confidence_score, provenance,
                       review_state, reviewed_by, reviewed_at, review_note,
                       created_at, updated_at
                FROM oc_genomics.molecular_evidence_candidates
                WHERE {where_sql}
                ORDER BY
                    CASE review_state
                        WHEN 'needs_review' THEN 0
                        WHEN 'candidate' THEN 1
                        WHEN 'accepted' THEN 2
                        ELSE 3
                    END,
                    confidence_score DESC,
                    created_at ASC,
                    association_id ASC
                LIMIT %s OFFSET %s
                """,
                (*params, query.limit, query.offset),
            )
            rows = tuple(dict(row) for row in cur.fetchall())
        return MolecularReviewQueuePage(
            total=total,
            limit=query.limit,
            offset=query.offset,
            items=rows,
        )

    def get(self, association_id: str) -> dict[str, Any] | None:
        MolecularEvidenceRepository(self.database_url).ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM oc_genomics.molecular_evidence_candidates
                WHERE association_id=%s
                """,
                (association_id,),
            )
            row = cur.fetchone()
        return dict(row) if row is not None else None
