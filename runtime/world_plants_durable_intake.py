"""Durable World Plants intake backed by migration 107 PostgreSQL storage.

This adapter preserves the existing inspect/get/list contract while using the
immutable ``taxonomy_pipeline.releases.source_payload`` as the authoritative
source store. It does not activate taxonomy or mutate the Knowledge Graph.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from runtime.world_plants_ingest import parse_world_orchids_release
from runtime.world_plants_staging import PostgresWorldPlantsStagingStore


class PostgresWorldPlantsIntakeStore:
    """Inspect and retain exact release bytes in PostgreSQL before staging."""

    def __init__(
        self,
        engine: Engine | None = None,
        *,
        max_upload_bytes: int = 75_000_000,
    ) -> None:
        self.staging = PostgresWorldPlantsStagingStore(engine)
        self.engine = self.staging.engine
        self.max_upload_bytes = max_upload_bytes

    def inspect_and_store(
        self,
        payload: bytes,
        *,
        filename: str,
        version_label: str,
        acquired_at: str,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if not payload:
            raise ValueError("taxonomy release file is empty")
        if len(payload) > self.max_upload_bytes:
            raise ValueError("taxonomy release file exceeds configured size limit")
        release_id, parsed = self.staging.register_release(
            payload,
            version_label=version_label,
            filename=filename,
            acquired_at=acquired_at,
        )
        report = self.get(release_id)
        if report is None:
            raise RuntimeError("durable taxonomy release registration was not readable")
        report["inspection"] = parsed.summary()
        report["issues"] = list(parsed.issues)
        report["notes"] = notes
        report["durable_storage"] = "postgresql"
        return report

    @staticmethod
    def _row_to_report(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "release_id": str(row["release_id"]),
            "state": str(row["state"]),
            "snapshot": {
                "sha256": str(row["source_sha256"]),
                "version_label": str(row["version_label"]),
                "filename": str(row["filename"]),
                "acquired_at": str(row["acquired_at"]),
                "source_encoding": str(row["source_encoding"]),
                "row_count": int(row["source_row_count"]),
            },
            "canonical_promotion": "blocked_pending_staging_comparison_and_owner_approval",
            "automatic_promotion": False,
            "durable_storage": "postgresql",
        }

    def get(self, release_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT release_id, source_sha256, version_label, filename, acquired_at, "
                        "source_encoding, source_row_count, state "
                        "FROM taxonomy_pipeline.releases WHERE release_id = :release_id"
                    ),
                    {"release_id": release_id},
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._row_to_report(dict(row))

    def get_with_inspection(self, release_id: str) -> dict[str, Any] | None:
        report = self.get(release_id)
        if report is None:
            return None
        parsed = parse_world_orchids_release(self.source_bytes(release_id))
        report["inspection"] = parsed.summary()
        report["issues"] = list(parsed.issues)
        return report

    def list_reports(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT release_id, source_sha256, version_label, filename, acquired_at, "
                        "source_encoding, source_row_count, state "
                        "FROM taxonomy_pipeline.releases "
                        "ORDER BY acquired_at DESC, created_at DESC"
                    )
                )
                .mappings()
                .all()
            )
        return [self._row_to_report(dict(row)) for row in rows]

    def source_bytes(self, release_id: str) -> bytes:
        return self.staging.source_payload(release_id)

    def stage_next_batch(self, release_id: str, *, batch_size: int):
        return self.staging.stage_next_batch(release_id, batch_size=batch_size)

    def checkpoint(self, release_id: str) -> dict[str, Any]:
        return self.staging.checkpoint(release_id)

    def counts(self, release_id: str) -> dict[str, int]:
        return self.staging.counts(release_id)

    def change_report(self, release_id: str) -> dict[str, Any] | None:
        return self.staging.change_report(release_id)
