"""Durable PostgreSQL persistence for bounded occurrence staging.

This module persists staging evidence only. It does not write to the production
Knowledge Graph or activate taxonomy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.database import get_engine
from runtime.occurrence_staging import OccurrenceStagingResult, stage_occurrence_batch


@dataclass(frozen=True)
class OccurrencePersistenceReceipt:
    source: str
    job_key: str
    staged_upserts: int
    review_upserts: int
    checkpoint_batch_end: int
    duplicate_skipped: int
    no_production_graph_mutation: bool = True


class PostgresOccurrenceStagingStore:
    """Persist normalized occurrences, raw provenance, review items and checkpoints."""

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or get_engine()
        if self.engine.dialect.name != "postgresql":
            raise ValueError("durable occurrence staging requires PostgreSQL")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    def seen_checksums(self, source: str) -> set[str]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT acquisition_checksum "
                    "FROM occurrence_pipeline.staged_occurrences WHERE source = :source"
                ),
                {"source": source},
            ).fetchall()
        return {str(row[0]).strip() for row in rows}

    def load_checkpoint(self, source: str, job_key: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT batch_start, batch_end, staged_count, duplicate_skipped, "
                    "completed, state, updated_at "
                    "FROM occurrence_pipeline.checkpoints "
                    "WHERE source = :source AND job_key = :job_key"
                ),
                {"source": source, "job_key": job_key},
            ).mappings().first()
        if row is None:
            return None
        state = dict(row["state"] or {})
        return {
            "source": source,
            "job_key": job_key,
            "batch_start": int(row["batch_start"]),
            "batch_end": int(row["batch_end"]),
            "staged_count": int(row["staged_count"]),
            "duplicate_skipped": int(row["duplicate_skipped"]),
            "completed": bool(row["completed"]),
            "state": state,
            "updated_at": row["updated_at"].isoformat(),
        }

    def persist_result(
        self,
        result: OccurrenceStagingResult,
        *,
        job_key: str,
        completed: bool = False,
    ) -> OccurrencePersistenceReceipt:
        staged_upserts = 0
        review_upserts = 0
        with self.engine.begin() as connection:
            for occurrence in result.staged:
                payload = occurrence.as_dict()
                raw = dict(payload.pop("raw") or {})
                connection.execute(
                    text(
                        """
                        INSERT INTO occurrence_pipeline.staged_occurrences (
                            source, source_record_id, scientific_name, accepted_name,
                            taxon_key, canonical_taxon_id, reconciliation_state,
                            latitude, longitude, country_code, locality, event_date,
                            recorded_by, license, basis_of_record, acquisition_checksum,
                            raw_payload, normalized_payload
                        ) VALUES (
                            :source, :source_record_id, :scientific_name, :accepted_name,
                            :taxon_key, :canonical_taxon_id, :reconciliation_state,
                            :latitude, :longitude, :country_code, :locality, :event_date,
                            :recorded_by, :license, :basis_of_record, :acquisition_checksum,
                            CAST(:raw_payload AS jsonb), CAST(:normalized_payload AS jsonb)
                        )
                        ON CONFLICT (source, source_record_id) DO UPDATE SET
                            scientific_name = EXCLUDED.scientific_name,
                            accepted_name = EXCLUDED.accepted_name,
                            taxon_key = EXCLUDED.taxon_key,
                            canonical_taxon_id = EXCLUDED.canonical_taxon_id,
                            reconciliation_state = EXCLUDED.reconciliation_state,
                            latitude = EXCLUDED.latitude,
                            longitude = EXCLUDED.longitude,
                            country_code = EXCLUDED.country_code,
                            locality = EXCLUDED.locality,
                            event_date = EXCLUDED.event_date,
                            recorded_by = EXCLUDED.recorded_by,
                            license = EXCLUDED.license,
                            basis_of_record = EXCLUDED.basis_of_record,
                            acquisition_checksum = EXCLUDED.acquisition_checksum,
                            raw_payload = EXCLUDED.raw_payload,
                            normalized_payload = EXCLUDED.normalized_payload,
                            last_seen_at = now()
                        """
                    ),
                    {
                        **payload,
                        "raw_payload": self._json(raw),
                        "normalized_payload": self._json(payload),
                    },
                )
                staged_upserts += 1

            for item in result.review_queue:
                payload = item.as_dict()
                connection.execute(
                    text(
                        """
                        INSERT INTO occurrence_pipeline.review_queue (
                            source, source_record_id, scientific_name, reason,
                            review_state, suggested_action
                        ) VALUES (
                            :source, :source_record_id, :scientific_name, :reason,
                            :review_state, :suggested_action
                        )
                        ON CONFLICT (source, source_record_id) DO UPDATE SET
                            scientific_name = EXCLUDED.scientific_name,
                            reason = EXCLUDED.reason,
                            review_state = EXCLUDED.review_state,
                            suggested_action = EXCLUDED.suggested_action,
                            status = 'open',
                            updated_at = now()
                        """
                    ),
                    payload,
                )
                review_upserts += 1

            checkpoint_state = dict(result.checkpoint)
            connection.execute(
                text(
                    """
                    INSERT INTO occurrence_pipeline.checkpoints (
                        source, job_key, batch_start, batch_end, staged_count,
                        duplicate_skipped, completed, state
                    ) VALUES (
                        :source, :job_key, :batch_start, :batch_end, :staged_count,
                        :duplicate_skipped, :completed, CAST(:state AS jsonb)
                    )
                    ON CONFLICT (source, job_key) DO UPDATE SET
                        batch_start = EXCLUDED.batch_start,
                        batch_end = EXCLUDED.batch_end,
                        staged_count = EXCLUDED.staged_count,
                        duplicate_skipped = EXCLUDED.duplicate_skipped,
                        completed = EXCLUDED.completed,
                        state = EXCLUDED.state,
                        updated_at = now()
                    """
                ),
                {
                    "source": result.source,
                    "job_key": job_key,
                    "batch_start": result.batch_start,
                    "batch_end": result.batch_end,
                    "staged_count": len(result.staged),
                    "duplicate_skipped": result.duplicate_skipped,
                    "completed": completed,
                    "state": self._json(checkpoint_state),
                },
            )

        return OccurrencePersistenceReceipt(
            source=result.source,
            job_key=job_key,
            staged_upserts=staged_upserts,
            review_upserts=review_upserts,
            checkpoint_batch_end=result.batch_end,
            duplicate_skipped=result.duplicate_skipped,
        )

    def counts(self, source: str) -> dict[str, int]:
        with self.engine.connect() as connection:
            staged = connection.execute(
                text(
                    "SELECT count(*) FROM occurrence_pipeline.staged_occurrences "
                    "WHERE source = :source"
                ),
                {"source": source},
            ).scalar_one()
            review = connection.execute(
                text(
                    "SELECT count(*) FROM occurrence_pipeline.review_queue "
                    "WHERE source = :source AND status = 'open'"
                ),
                {"source": source},
            ).scalar_one()
        return {"staged": int(staged), "open_review": int(review)}


def stage_and_persist_occurrences(
    records: Iterable[Mapping[str, Any]],
    *,
    source: str,
    store: PostgresOccurrenceStagingStore,
    job_key: str,
    canonical_lookup: Mapping[str, str] | None = None,
    completed: bool = False,
) -> tuple[OccurrenceStagingResult, OccurrencePersistenceReceipt]:
    """Stage one bounded batch using durable checkpoint and deduplication state."""

    prior = store.load_checkpoint(source, job_key)
    batch_start = int(prior["batch_end"]) if prior else 0
    result = stage_occurrence_batch(
        records,
        source=source,
        batch_start=batch_start,
        seen_checksums=store.seen_checksums(source),
        canonical_lookup=canonical_lookup,
    )
    receipt = store.persist_result(result, job_key=job_key, completed=completed)
    return result, receipt
