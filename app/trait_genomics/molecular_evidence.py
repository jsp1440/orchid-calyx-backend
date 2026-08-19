from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, model_validator

MOLECULAR_DDL = """
CREATE SCHEMA IF NOT EXISTS oc_genomics;
CREATE TABLE IF NOT EXISTS oc_genomics.molecular_evidence_candidates (
    association_id text PRIMARY KEY,
    canonical_taxon_id text NOT NULL,
    scientific_name text,
    evidence_kind text NOT NULL CHECK (evidence_kind IN ('genetic_association','expression_association','selection_association')),
    trait_predicate text NOT NULL,
    trait_value text,
    association_type text NOT NULL,
    gene_id text,
    protein_id text,
    sequence_accession text,
    pathway_id text,
    marker_name text,
    effect_value text,
    evidence_text text NOT NULL,
    method text,
    source_id text NOT NULL,
    source_uri text,
    doi text,
    pmid text,
    publication_id text,
    confidence_score double precision NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 1),
    provenance jsonb NOT NULL DEFAULT '{}'::jsonb,
    review_state text NOT NULL DEFAULT 'candidate' CHECK (review_state IN ('candidate','accepted','rejected','needs_review')),
    reviewed_by text,
    reviewed_at timestamptz,
    review_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (gene_id IS NOT NULL OR protein_id IS NOT NULL OR pathway_id IS NOT NULL OR marker_name IS NOT NULL OR sequence_accession IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_tig_molecular_candidate_taxon
    ON oc_genomics.molecular_evidence_candidates (canonical_taxon_id);
CREATE INDEX IF NOT EXISTS idx_tig_molecular_candidate_review
    ON oc_genomics.molecular_evidence_candidates (review_state, evidence_kind);
CREATE OR REPLACE VIEW oc_genomics.trait_associations AS
SELECT association_id, canonical_taxon_id, scientific_name, trait_predicate, trait_value,
       association_type, gene_id, protein_id, sequence_accession, pathway_id, marker_name,
       effect_value, evidence_text, method, source_id, source_uri, doi, pmid, publication_id,
       confidence_score, review_state, provenance, reviewed_by, reviewed_at
FROM oc_genomics.molecular_evidence_candidates
WHERE review_state='accepted' AND evidence_kind IN ('genetic_association','selection_association');
CREATE OR REPLACE VIEW oc_genomics.expression_associations AS
SELECT association_id, canonical_taxon_id, scientific_name, trait_predicate, trait_value,
       association_type, gene_id, protein_id, sequence_accession, pathway_id, marker_name,
       effect_value, evidence_text, method, source_id, source_uri, doi, pmid, publication_id,
       confidence_score, review_state, provenance, reviewed_by, reviewed_at
FROM oc_genomics.molecular_evidence_candidates
WHERE review_state='accepted' AND evidence_kind='expression_association';
"""


class MolecularEvidenceCandidate(BaseModel):
    association_id: str | None = None
    canonical_taxon_id: str = Field(min_length=1)
    scientific_name: str | None = None
    evidence_kind: Literal[
        "genetic_association",
        "expression_association",
        "selection_association",
    ]
    trait_predicate: str = Field(min_length=1)
    trait_value: str | None = None
    association_type: str = Field(min_length=1)
    gene_id: str | None = None
    protein_id: str | None = None
    sequence_accession: str | None = None
    pathway_id: str | None = None
    marker_name: str | None = None
    effect_value: str | None = None
    evidence_text: str = Field(min_length=1)
    method: str | None = None
    source_id: str = Field(min_length=1)
    source_uri: str | None = None
    doi: str | None = None
    pmid: str | None = None
    publication_id: str | None = None
    confidence_score: float = Field(ge=0.0, le=1.0)
    provenance: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_molecular_feature(self):
        if not any(
            (
                self.gene_id,
                self.protein_id,
                self.sequence_accession,
                self.pathway_id,
                self.marker_name,
            )
        ):
            raise ValueError("At least one molecular feature identifier is required")
        return self

    def stable_id(self) -> str:
        if self.association_id:
            return self.association_id
        payload = self.model_dump(mode="json", exclude={"association_id"})
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:24]
        return f"tig-mol:{digest}"


class MolecularReviewDecision(BaseModel):
    review_state: Literal["accepted", "rejected", "needs_review"]
    reviewed_by: str = Field(min_length=1)
    review_note: str = Field(min_length=1)


@dataclass(frozen=True)
class MolecularEvidenceSummary:
    total: int
    candidate: int
    accepted: int
    rejected: int
    needs_review: int
    genetic_association: int
    expression_association: int
    selection_association: int


class MolecularEvidenceRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")

    def _connect(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for molecular evidence persistence")
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def ensure_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(MOLECULAR_DDL)
            conn.commit()

    def upsert_candidate(self, candidate: MolecularEvidenceCandidate) -> dict[str, Any]:
        self.ensure_schema()
        association_id = candidate.stable_id()
        values = candidate.model_dump(mode="json")
        values["association_id"] = association_id
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_genomics.molecular_evidence_candidates (
                    association_id, canonical_taxon_id, scientific_name, evidence_kind,
                    trait_predicate, trait_value, association_type, gene_id, protein_id,
                    sequence_accession, pathway_id, marker_name, effect_value, evidence_text,
                    method, source_id, source_uri, doi, pmid, publication_id,
                    confidence_score, provenance
                ) VALUES (
                    %(association_id)s, %(canonical_taxon_id)s, %(scientific_name)s,
                    %(evidence_kind)s, %(trait_predicate)s, %(trait_value)s,
                    %(association_type)s, %(gene_id)s, %(protein_id)s,
                    %(sequence_accession)s, %(pathway_id)s, %(marker_name)s,
                    %(effect_value)s, %(evidence_text)s, %(method)s, %(source_id)s,
                    %(source_uri)s, %(doi)s, %(pmid)s, %(publication_id)s,
                    %(confidence_score)s, %(provenance)s
                )
                ON CONFLICT (association_id) DO UPDATE SET
                    canonical_taxon_id=EXCLUDED.canonical_taxon_id,
                    scientific_name=EXCLUDED.scientific_name,
                    evidence_kind=EXCLUDED.evidence_kind,
                    trait_predicate=EXCLUDED.trait_predicate,
                    trait_value=EXCLUDED.trait_value,
                    association_type=EXCLUDED.association_type,
                    gene_id=EXCLUDED.gene_id,
                    protein_id=EXCLUDED.protein_id,
                    sequence_accession=EXCLUDED.sequence_accession,
                    pathway_id=EXCLUDED.pathway_id,
                    marker_name=EXCLUDED.marker_name,
                    effect_value=EXCLUDED.effect_value,
                    evidence_text=EXCLUDED.evidence_text,
                    method=EXCLUDED.method,
                    source_id=EXCLUDED.source_id,
                    source_uri=EXCLUDED.source_uri,
                    doi=EXCLUDED.doi,
                    pmid=EXCLUDED.pmid,
                    publication_id=EXCLUDED.publication_id,
                    confidence_score=EXCLUDED.confidence_score,
                    provenance=EXCLUDED.provenance,
                    updated_at=now()
                RETURNING *
                """,
                {**values, "provenance": Jsonb(candidate.provenance)},
            )
            row = cur.fetchone()
            conn.commit()
        return dict(row)

    def review(self, association_id: str, decision: MolecularReviewDecision) -> dict[str, Any]:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE oc_genomics.molecular_evidence_candidates
                SET review_state=%s, reviewed_by=%s, review_note=%s,
                    reviewed_at=now(), updated_at=now()
                WHERE association_id=%s
                RETURNING *
                """,
                (
                    decision.review_state,
                    decision.reviewed_by,
                    decision.review_note,
                    association_id,
                ),
            )
            row = cur.fetchone()
            conn.commit()
        if row is None:
            raise KeyError(association_id)
        return dict(row)

    def summary(self) -> MolecularEvidenceSummary:
        self.ensure_schema()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    count(*) AS total,
                    count(*) FILTER (WHERE review_state='candidate') AS candidate,
                    count(*) FILTER (WHERE review_state='accepted') AS accepted,
                    count(*) FILTER (WHERE review_state='rejected') AS rejected,
                    count(*) FILTER (WHERE review_state='needs_review') AS needs_review,
                    count(*) FILTER (WHERE evidence_kind='genetic_association') AS genetic_association,
                    count(*) FILTER (WHERE evidence_kind='expression_association') AS expression_association,
                    count(*) FILTER (WHERE evidence_kind='selection_association') AS selection_association
                FROM oc_genomics.molecular_evidence_candidates
                """
            )
            row = cur.fetchone()
        return MolecularEvidenceSummary(**dict(row))
