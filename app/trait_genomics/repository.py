from __future__ import annotations

from contextlib import contextmanager
import os
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .models import DiscoveryDataset, DiscoveryHypothesis


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

CREATE TABLE IF NOT EXISTS calyx_scientific_archive_releases (
    release_id text PRIMARY KEY,
    dataset_id text NOT NULL,
    provider text NOT NULL,
    deposition_id bigint NOT NULL,
    release_fingerprint text NOT NULL,
    state text NOT NULL,
    community text,
    manifest jsonb NOT NULL,
    provider_payload jsonb NOT NULL,
    release_path text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, deposition_id),
    UNIQUE (provider, release_fingerprint)
);
CREATE INDEX IF NOT EXISTS idx_calyx_archive_dataset
    ON calyx_scientific_archive_releases (dataset_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_calyx_archive_state
    ON calyx_scientific_archive_releases (state);
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
                            dataset_id=EXCLUDED.dataset_id,
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

    def find_archive_release_by_fingerprint(
        self,
        release_fingerprint: str,
        *,
        provider: str = "zenodo",
    ) -> dict[str, Any] | None:
        self.ensure_schema()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT release_id, dataset_id, provider, deposition_id,
                       release_fingerprint, state, community, manifest,
                       provider_payload, release_path, created_at, updated_at
                FROM calyx_scientific_archive_releases
                WHERE provider=%s AND release_fingerprint=%s
                """,
                (provider, release_fingerprint),
            )
            row = cur.fetchone()
        if row is None:
            return None
        keys = (
            "release_id",
            "dataset_id",
            "provider",
            "deposition_id",
            "release_fingerprint",
            "state",
            "community",
            "manifest",
            "provider_payload",
            "release_path",
            "created_at",
            "updated_at",
        )
        return dict(zip(keys, row, strict=True))

    def save_archive_release(
        self,
        *,
        dataset_id: str,
        deposition_id: int,
        release_fingerprint: str,
        state: str,
        community: str | None,
        manifest: dict[str, Any],
        provider_payload: dict[str, Any],
        release_path: str,
        provider: str = "zenodo",
    ) -> dict[str, Any]:
        self.ensure_schema()
        release_id = f"{provider}:{deposition_id}"
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO calyx_scientific_archive_releases
                        (release_id, dataset_id, provider, deposition_id,
                         release_fingerprint, state, community, manifest,
                         provider_payload, release_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (provider, deposition_id) DO UPDATE SET
                        dataset_id=EXCLUDED.dataset_id,
                        release_fingerprint=EXCLUDED.release_fingerprint,
                        state=EXCLUDED.state,
                        community=EXCLUDED.community,
                        manifest=EXCLUDED.manifest,
                        provider_payload=EXCLUDED.provider_payload,
                        release_path=EXCLUDED.release_path,
                        updated_at=now()
                    RETURNING release_id, dataset_id, provider, deposition_id,
                              release_fingerprint, state, community, manifest,
                              provider_payload, release_path, created_at, updated_at
                    """,
                    (
                        release_id,
                        dataset_id,
                        provider,
                        deposition_id,
                        release_fingerprint,
                        state,
                        community,
                        Jsonb(manifest),
                        Jsonb(provider_payload),
                        release_path,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        keys = (
            "release_id",
            "dataset_id",
            "provider",
            "deposition_id",
            "release_fingerprint",
            "state",
            "community",
            "manifest",
            "provider_payload",
            "release_path",
            "created_at",
            "updated_at",
        )
        return dict(zip(keys, row, strict=True))
