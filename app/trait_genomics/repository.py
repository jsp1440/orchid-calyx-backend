from __future__ import annotations

import json
import os
from contextlib import contextmanager

import psycopg
from psycopg.types.json import Jsonb

from .models import DiscoveryDataset, DiscoveryHypothesis, EvidenceRecord


DDL = """
CREATE TABLE IF NOT EXISTS calyx_trait_evidence (
    evidence_id text PRIMARY KEY,
    taxon_id text NOT NULL,
    kind text NOT NULL,
    predicate text NOT NULL,
    payload jsonb NOT NULL,
    source_id text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_calyx_trait_evidence_taxon ON calyx_trait_evidence (taxon_id);
CREATE INDEX IF NOT EXISTS idx_calyx_trait_evidence_kind ON calyx_trait_evidence (kind);
CREATE TABLE IF NOT EXISTS calyx_trait_genomics_hypotheses (
    hypothesis_id text PRIMARY KEY,
    dataset_id text NOT NULL,
    payload jsonb NOT NULL,
    confidence double precision NOT NULL,
    status text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_calyx_tig_dataset ON calyx_trait_genomics_hypotheses (dataset_id);
"""


class TraitGenomicsRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.getenv("DATABASE_URL")

    @contextmanager
    def connection(self):
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for trait-genomics persistence")
        with psycopg.connect(self.database_url) as conn:
            yield conn

    def ensure_schema(self) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(DDL)
            conn.commit()

    def save_dataset(self, dataset: DiscoveryDataset) -> int:
        self.ensure_schema()
        written = 0
        with self.connection() as conn:
            with conn.cursor() as cur:
                for record in dataset.records:
                    cur.execute(
                        """
                        INSERT INTO calyx_trait_evidence
                            (evidence_id, taxon_id, kind, predicate, payload, source_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (evidence_id) DO UPDATE SET
                            taxon_id=EXCLUDED.taxon_id,
                            kind=EXCLUDED.kind,
                            predicate=EXCLUDED.predicate,
                            payload=EXCLUDED.payload,
                            source_id=EXCLUDED.source_id
                        """,
                        (
                            record.evidence_id,
                            record.taxon_id,
                            record.kind.value,
                            record.predicate,
                            Jsonb(record.model_dump(mode="json")),
                            record.source_id,
                        ),
                    )
                    written += 1
            conn.commit()
        return written

    def save_hypotheses(self, dataset_id: str, hypotheses: list[DiscoveryHypothesis]) -> int:
        self.ensure_schema()
        with self.connection() as conn:
            with conn.cursor() as cur:
                for hypothesis in hypotheses:
                    cur.execute(
                        """
                        INSERT INTO calyx_trait_genomics_hypotheses
                            (hypothesis_id, dataset_id, payload, confidence, status)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (hypothesis_id) DO UPDATE SET
                            payload=EXCLUDED.payload,
                            confidence=EXCLUDED.confidence,
                            status=EXCLUDED.status,
                            updated_at=now()
                        """,
                        (
                            hypothesis.hypothesis_id,
                            dataset_id,
                            Jsonb(hypothesis.model_dump(mode="json")),
                            hypothesis.confidence,
                            hypothesis.status,
                        ),
                    )
            conn.commit()
        return len(hypotheses)
