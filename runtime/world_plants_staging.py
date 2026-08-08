"""Durable, bounded World Plants/Hassler release staging.

This module stages immutable release evidence in PostgreSQL. It intentionally has
no taxonomy activation or Knowledge Graph mutation operation.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.database import get_engine
from runtime.world_plants_ingest import ParseResult, WorldPlantsRow, parse_world_orchids_release

MAX_BATCH_SIZE = 2_000


@dataclass(frozen=True)
class TaxonomyStagingReceipt:
    release_id: str
    batch_start: int
    batch_end: int
    staged_upserts: int
    completed: bool
    total_staged: int
    review_items: int
    automatic_promotion: bool = False
    no_production_taxonomy_mutation: bool = True
    no_knowledge_graph_mutation: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "release_id": self.release_id,
            "batch_start": self.batch_start,
            "batch_end": self.batch_end,
            "staged_upserts": self.staged_upserts,
            "completed": self.completed,
            "total_staged": self.total_staged,
            "review_items": self.review_items,
            "automatic_promotion": self.automatic_promotion,
            "no_production_taxonomy_mutation": self.no_production_taxonomy_mutation,
            "no_knowledge_graph_mutation": self.no_knowledge_graph_mutation,
        }


def _canonical_row_payload(row: WorldPlantsRow) -> str:
    return json.dumps(row.values, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _row_checksum(row: WorldPlantsRow) -> str:
    return hashlib.sha256(_canonical_row_payload(row).encode("utf-8")).hexdigest()


def _identity(row: WorldPlantsRow) -> tuple[str, str]:
    return row.taxon_code, row.name


def _index_rows(rows: Iterable[WorldPlantsRow]) -> dict[tuple[str, str], WorldPlantsRow]:
    return {_identity(row): row for row in rows}


def build_change_report(
    current: Iterable[WorldPlantsRow],
    baseline: Iterable[WorldPlantsRow] = (),
    *,
    current_issues: Iterable[dict[str, Any]] = (),
    baseline_release_id: str | None = None,
) -> dict[str, Any]:
    """Build a review-first release delta without inferring unsupported synonymy."""

    current_rows = tuple(current)
    baseline_rows = tuple(baseline)
    current_index = _index_rows(current_rows)
    baseline_index = _index_rows(baseline_rows)
    current_keys = set(current_index)
    baseline_keys = set(baseline_index)

    added = sorted(current_keys - baseline_keys)
    removed = sorted(baseline_keys - current_keys)
    shared = sorted(current_keys & baseline_keys)

    synonym_changes: list[dict[str, Any]] = []
    status_changes: list[dict[str, Any]] = []
    distribution_changes: list[dict[str, Any]] = []
    changed_records = 0
    for key in shared:
        old = baseline_index[key].values
        new = current_index[key].values
        if old != new:
            changed_records += 1
        if old.get("synonyms_raw") != new.get("synonyms_raw"):
            synonym_changes.append(
                {"taxon_code": key[0], "name": key[1], "before": old.get("synonyms_raw", ""), "after": new.get("synonyms_raw", "")}
            )
        if old.get("status_raw") != new.get("status_raw"):
            status_changes.append(
                {"taxon_code": key[0], "name": key[1], "before": old.get("status_raw", ""), "after": new.get("status_raw", "")}
            )
        if old.get("distribution") != new.get("distribution"):
            distribution_changes.append(
                {"taxon_code": key[0], "name": key[1], "before": old.get("distribution", ""), "after": new.get("distribution", "")}
            )

    old_by_number = {
        row.values.get("world_plants_number", ""): row
        for row in baseline_rows
        if row.values.get("world_plants_number")
    }
    accepted_name_change_candidates: list[dict[str, Any]] = []
    for row in current_rows:
        number = row.values.get("world_plants_number", "")
        old = old_by_number.get(number) if number else None
        if old and old.name != row.name:
            accepted_name_change_candidates.append(
                {
                    "world_plants_number": number,
                    "taxon_code": row.taxon_code,
                    "before": old.name,
                    "after": row.name,
                    "review_required": True,
                }
            )

    duplicate_counter = Counter(_identity(row) for row in current_rows)
    duplicate_identities = [
        {"taxon_code": key[0], "name": key[1], "count": count}
        for key, count in sorted(duplicate_counter.items())
        if count > 1
    ]
    issues = list(current_issues)
    malformed = [item for item in issues if item.get("reason") in {"unexpected_row_width", "missing_name", "unknown_rank_code"}]

    return {
        "baseline_release_id": baseline_release_id,
        "summary": {
            "current_rows": len(current_rows),
            "baseline_rows": len(baseline_rows),
            "added_taxa": len(added),
            "removed_taxa": len(removed),
            "changed_records": changed_records,
            "synonym_changes": len(synonym_changes),
            "status_changes": len(status_changes),
            "distribution_changes": len(distribution_changes),
            "accepted_name_change_candidates": len(accepted_name_change_candidates),
            "duplicate_identities": len(duplicate_identities),
            "malformed_rows": len(malformed),
        },
        "added_taxa": [{"taxon_code": code, "name": name} for code, name in added],
        "removed_taxa": [{"taxon_code": code, "name": name} for code, name in removed],
        "accepted_name_change_candidates": accepted_name_change_candidates,
        "synonym_changes": synonym_changes,
        "status_changes": status_changes,
        "distribution_changes": distribution_changes,
        "duplicate_identities": duplicate_identities,
        "malformed_rows": malformed,
        "interpretation_note": (
            "Accepted-name changes are reported only when the same non-empty World Plants number changes name. "
            "Rows without a stable source number are never heuristically paired; they remain explicit added/removed taxa for review."
        ),
        "owner_approval_required_for_activation": True,
        "automatic_promotion": False,
    }


class PostgresWorldPlantsStagingStore:
    """Versioned staging store for an immutable Hassler release source payload."""

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or get_engine()
        if self.engine.dialect.name != "postgresql":
            raise ValueError("durable World Plants staging requires PostgreSQL")

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)

    def register_release(
        self,
        payload: bytes,
        *,
        version_label: str,
        filename: str,
        acquired_at: str,
    ) -> tuple[str, ParseResult]:
        parsed = parse_world_orchids_release(payload)
        release_id = hashlib.sha256(payload).hexdigest()
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO taxonomy_pipeline.releases (
                        release_id, source_sha256, version_label, filename, acquired_at,
                        source_encoding, source_row_count, source_payload
                    ) VALUES (
                        :release_id, :source_sha256, :version_label, :filename, :acquired_at,
                        :source_encoding, :source_row_count, :source_payload
                    )
                    ON CONFLICT (release_id) DO UPDATE SET
                        version_label = EXCLUDED.version_label,
                        filename = EXCLUDED.filename,
                        acquired_at = EXCLUDED.acquired_at,
                        updated_at = now()
                    """
                ),
                {
                    "release_id": release_id,
                    "source_sha256": release_id,
                    "version_label": version_label,
                    "filename": filename,
                    "acquired_at": acquired_at,
                    "source_encoding": parsed.source_encoding,
                    "source_row_count": len(parsed.rows),
                    "source_payload": payload,
                },
            )
            connection.execute(
                text(
                    """
                    INSERT INTO taxonomy_pipeline.staging_checkpoints (release_id)
                    VALUES (:release_id)
                    ON CONFLICT (release_id) DO NOTHING
                    """
                ),
                {"release_id": release_id},
            )
        return release_id, parsed

    def source_payload(self, release_id: str) -> bytes:
        with self.engine.connect() as connection:
            payload = connection.execute(
                text("SELECT source_payload FROM taxonomy_pipeline.releases WHERE release_id = :release_id"),
                {"release_id": release_id},
            ).scalar_one_or_none()
        if payload is None:
            raise KeyError(f"taxonomy release not found: {release_id}")
        return bytes(payload)

    def checkpoint(self, release_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT next_row_index, staged_count, completed, updated_at "
                    "FROM taxonomy_pipeline.staging_checkpoints WHERE release_id = :release_id"
                ),
                {"release_id": release_id},
            ).mappings().one()
        return {
            "next_row_index": int(row["next_row_index"]),
            "staged_count": int(row["staged_count"]),
            "completed": bool(row["completed"]),
            "updated_at": row["updated_at"].isoformat(),
        }

    def stage_next_batch(self, release_id: str, *, batch_size: int = 1_000) -> TaxonomyStagingReceipt:
        if not 1 <= batch_size <= MAX_BATCH_SIZE:
            raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
        payload = self.source_payload(release_id)
        parsed = parse_world_orchids_release(payload)
        checkpoint = self.checkpoint(release_id)
        start = checkpoint["next_row_index"]
        end = min(start + batch_size, len(parsed.rows))
        batch = parsed.rows[start:end]

        with self.engine.begin() as connection:
            for row in batch:
                connection.execute(
                    text(
                        """
                        INSERT INTO taxonomy_pipeline.staged_taxa (
                            release_id, source_row_number, taxon_code, world_plants_number,
                            scientific_name, row_checksum, normalized_payload
                        ) VALUES (
                            :release_id, :source_row_number, :taxon_code, :world_plants_number,
                            :scientific_name, :row_checksum, CAST(:normalized_payload AS jsonb)
                        )
                        ON CONFLICT (release_id, source_row_number) DO UPDATE SET
                            taxon_code = EXCLUDED.taxon_code,
                            world_plants_number = EXCLUDED.world_plants_number,
                            scientific_name = EXCLUDED.scientific_name,
                            row_checksum = EXCLUDED.row_checksum,
                            normalized_payload = EXCLUDED.normalized_payload
                        """
                    ),
                    {
                        "release_id": release_id,
                        "source_row_number": row.source_row_number,
                        "taxon_code": row.taxon_code,
                        "world_plants_number": row.values.get("world_plants_number") or None,
                        "scientific_name": row.name,
                        "row_checksum": _row_checksum(row),
                        "normalized_payload": self._json(row.values),
                    },
                )

            completed = end >= len(parsed.rows)
            connection.execute(
                text(
                    """
                    UPDATE taxonomy_pipeline.staging_checkpoints
                    SET next_row_index = :next_row_index,
                        staged_count = (SELECT count(*) FROM taxonomy_pipeline.staged_taxa WHERE release_id = :release_id),
                        completed = :completed,
                        updated_at = now()
                    WHERE release_id = :release_id
                    """
                ),
                {"release_id": release_id, "next_row_index": end, "completed": completed},
            )
            connection.execute(
                text(
                    "UPDATE taxonomy_pipeline.releases SET state = :state, updated_at = now() WHERE release_id = :release_id"
                ),
                {"release_id": release_id, "state": "staged" if completed else "staging"},
            )

        if completed:
            self.generate_change_report(release_id)
        counts = self.counts(release_id)
        return TaxonomyStagingReceipt(
            release_id=release_id,
            batch_start=start,
            batch_end=end,
            staged_upserts=len(batch),
            completed=completed,
            total_staged=counts["staged"],
            review_items=counts["open_review"],
        )

    def staged_rows(self, release_id: str) -> tuple[WorldPlantsRow, ...]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT source_row_number, normalized_payload FROM taxonomy_pipeline.staged_taxa "
                    "WHERE release_id = :release_id ORDER BY source_row_number"
                ),
                {"release_id": release_id},
            ).mappings().all()
        return tuple(
            WorldPlantsRow(int(row["source_row_number"]), dict(row["normalized_payload"]))
            for row in rows
        )

    def _latest_completed_baseline(self, release_id: str) -> str | None:
        with self.engine.connect() as connection:
            return connection.execute(
                text(
                    """
                    SELECT release_id FROM taxonomy_pipeline.releases
                    WHERE release_id <> :release_id AND state IN ('staged', 'review_required', 'reviewed')
                    ORDER BY created_at DESC LIMIT 1
                    """
                ),
                {"release_id": release_id},
            ).scalar_one_or_none()

    def generate_change_report(self, release_id: str, baseline_release_id: str | None = None) -> dict[str, Any]:
        payload = self.source_payload(release_id)
        parsed = parse_world_orchids_release(payload)
        baseline_id = baseline_release_id or self._latest_completed_baseline(release_id)
        baseline_rows = self.staged_rows(baseline_id) if baseline_id else ()
        report = build_change_report(
            self.staged_rows(release_id),
            baseline_rows,
            current_issues=parsed.issues,
            baseline_release_id=baseline_id,
        )

        review_items: list[tuple[str, str, str, dict[str, Any]]] = []
        for item in report["duplicate_identities"]:
            key = f"duplicate:{item['taxon_code']}:{item['name']}"
            review_items.append((key, "duplicate_identity", f"Duplicate taxon identity: {item['taxon_code']} {item['name']}", item))
        for item in report["malformed_rows"]:
            key = f"malformed:{item.get('source_row_number', 'unknown')}:{item.get('reason', 'unknown')}"
            review_items.append((key, "malformed_row", f"Malformed source row requires review: {item.get('reason')}", item))
        for item in report["accepted_name_change_candidates"]:
            key = f"accepted-name:{item['world_plants_number']}"
            review_items.append((key, "accepted_name_change", f"Accepted-name change candidate: {item['before']} → {item['after']}", item))

        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO taxonomy_pipeline.change_reports (release_id, baseline_release_id, report)
                    VALUES (:release_id, :baseline_release_id, CAST(:report AS jsonb))
                    ON CONFLICT (release_id) DO UPDATE SET
                        baseline_release_id = EXCLUDED.baseline_release_id,
                        report = EXCLUDED.report,
                        generated_at = now()
                    """
                ),
                {"release_id": release_id, "baseline_release_id": baseline_id, "report": self._json(report)},
            )
            for review_key, category, summary, evidence in review_items:
                connection.execute(
                    text(
                        """
                        INSERT INTO taxonomy_pipeline.review_queue (
                            release_id, review_key, category, summary, evidence
                        ) VALUES (
                            :release_id, :review_key, :category, :summary, CAST(:evidence AS jsonb)
                        )
                        ON CONFLICT (release_id, review_key) DO UPDATE SET
                            category = EXCLUDED.category,
                            summary = EXCLUDED.summary,
                            evidence = EXCLUDED.evidence,
                            status = 'open',
                            updated_at = now()
                        """
                    ),
                    {
                        "release_id": release_id,
                        "review_key": review_key,
                        "category": category,
                        "summary": summary,
                        "evidence": self._json(evidence),
                    },
                )
            connection.execute(
                text("UPDATE taxonomy_pipeline.releases SET state = :state, updated_at = now() WHERE release_id = :release_id"),
                {"release_id": release_id, "state": "review_required" if review_items else "staged"},
            )
        return report

    def change_report(self, release_id: str) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            report = connection.execute(
                text("SELECT report FROM taxonomy_pipeline.change_reports WHERE release_id = :release_id"),
                {"release_id": release_id},
            ).scalar_one_or_none()
        return dict(report) if report is not None else None

    def counts(self, release_id: str) -> dict[str, int]:
        with self.engine.connect() as connection:
            staged = connection.execute(
                text("SELECT count(*) FROM taxonomy_pipeline.staged_taxa WHERE release_id = :release_id"),
                {"release_id": release_id},
            ).scalar_one()
            review = connection.execute(
                text("SELECT count(*) FROM taxonomy_pipeline.review_queue WHERE release_id = :release_id AND status = 'open'"),
                {"release_id": release_id},
            ).scalar_one()
        return {"staged": int(staged), "open_review": int(review)}
