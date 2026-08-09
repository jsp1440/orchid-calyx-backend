"""Durable occurrence staging bound to exact reviewed taxonomy evidence.

This module consolidates PostgreSQL occurrence durability with immutable
reconciliation evidence. It deliberately distinguishes provider taxon keys,
Hassler/World Plants source-taxonomy identity, and canonical Orchid Continuum
taxon identity. Staging evidence never invents the latter.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.database import get_engine
from runtime.occurrence_staging import SUPPORTED_SOURCES

OCCURRENCE_RECONCILIATION_SCHEMA_VERSION = "2.1.0"
MAX_BATCH_RECORDS = 5_000
CANONICAL_PROJECTION_BLOCKER = "CANONICAL_TAXON_CROSSWALK_NOT_ACTIVATED"


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_name(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _canonical_identifier(value: Any) -> str:
    return str(value or "").strip().casefold()


def _raw_sha(record: Mapping[str, Any]) -> str:
    return _sha256_text(_stable_json(dict(record)))


@dataclass(frozen=True, slots=True)
class TaxonomyReconciliationContext:
    release_id: str
    source_sha256: str
    release_state: str
    review_sha256: str
    open_review_count: int
    context_sha256: str
    by_number: dict[str, tuple[dict[str, str], ...]]
    by_name: dict[str, tuple[dict[str, str], ...]]
    blocked_numbers: frozenset[str]
    blocked_names: frozenset[str]


@dataclass(frozen=True, slots=True)
class OccurrenceRunReceipt:
    run_id: str
    source: str
    job_key: str
    input_batch_sha256: str
    taxonomy_release_id: str
    taxonomy_context_sha256: str
    staged_count: int
    review_count: int
    duplicate_skipped: int
    completed: bool
    canonical_projection_ready: bool = False
    canonical_projection_blocker: str = CANONICAL_PROJECTION_BLOCKER
    automatic_promotion: bool = False
    no_taxonomy_activation: bool = True
    no_knowledge_graph_mutation: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PostgresOccurrencePersistence:
    """Content-addressed, immutable occurrence reconciliation persistence."""

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or get_engine()
        if self.engine.dialect.name != "postgresql":
            raise ValueError("durable occurrence persistence requires PostgreSQL")

    @staticmethod
    def _review_digest(rows: list[Mapping[str, Any]]) -> str:
        payload = [
            {
                "review_key": str(row["review_key"]),
                "category": str(row["category"]),
                "summary": str(row["summary"]),
                "evidence": dict(row["evidence"] or {}),
                "status": str(row["status"]),
            }
            for row in rows
        ]
        return _sha256_text(_stable_json(payload))

    def taxonomy_context(self, release_id: str) -> TaxonomyReconciliationContext:
        with self.engine.connect() as connection:
            release = (
                connection.execute(
                    text(
                        "SELECT release_id, source_sha256, state "
                        "FROM taxonomy_pipeline.releases WHERE release_id = :release_id"
                    ),
                    {"release_id": release_id},
                )
                .mappings()
                .first()
            )
            if release is None:
                raise LookupError("TAXONOMY_RELEASE_NOT_FOUND")

            staged = (
                connection.execute(
                    text(
                        "SELECT source_row_number, taxon_code, world_plants_number, "
                        "scientific_name FROM taxonomy_pipeline.staged_taxa "
                        "WHERE release_id = :release_id ORDER BY source_row_number"
                    ),
                    {"release_id": release_id},
                )
                .mappings()
                .all()
            )
            reviews = (
                connection.execute(
                    text(
                        "SELECT review_key, category, summary, evidence, status "
                        "FROM taxonomy_pipeline.review_queue "
                        "WHERE release_id = :release_id ORDER BY review_key"
                    ),
                    {"release_id": release_id},
                )
                .mappings()
                .all()
            )

        if not staged:
            raise ValueError("TAXONOMY_RELEASE_NOT_STAGED")

        open_reviews = [row for row in reviews if str(row["status"]) == "open"]
        review_sha = self._review_digest(reviews)
        blocked_numbers: set[str] = set()
        blocked_names: set[str] = set()
        for row in open_reviews:
            evidence = dict(row["evidence"] or {})
            number = _canonical_identifier(evidence.get("world_plants_number"))
            if number:
                blocked_numbers.add(number)
            for key in ("name", "before", "after", "scientific_name"):
                name = _canonical_name(evidence.get(key))
                if name:
                    blocked_names.add(name)

        by_number_lists: dict[str, list[dict[str, str]]] = {}
        by_name_lists: dict[str, list[dict[str, str]]] = {}
        for row in staged:
            source_row = int(row["source_row_number"])
            rank_code = str(row["taxon_code"] or "").strip()
            number = str(row["world_plants_number"] or "").strip()
            name = str(row["scientific_name"]).strip()
            item = {
                "source_taxonomy_record_id": (
                    f"world-plants:{release_id}:row:{source_row}"
                ),
                "source_row_number": str(source_row),
                "world_plants_number": number,
                "taxon_rank_code": rank_code,
                "scientific_name": name,
            }
            if number:
                by_number_lists.setdefault(_canonical_identifier(number), []).append(item)
            by_name_lists.setdefault(_canonical_name(name), []).append(item)

        by_number = {key: tuple(value) for key, value in by_number_lists.items()}
        by_name = {key: tuple(value) for key, value in by_name_lists.items()}
        context_payload = {
            "release_id": str(release["release_id"]),
            "source_sha256": str(release["source_sha256"]),
            "release_state": str(release["state"]),
            "review_sha256": review_sha,
            "open_review_count": len(open_reviews),
            "schema_version": OCCURRENCE_RECONCILIATION_SCHEMA_VERSION,
        }
        return TaxonomyReconciliationContext(
            release_id=str(release["release_id"]),
            source_sha256=str(release["source_sha256"]),
            release_state=str(release["state"]),
            review_sha256=review_sha,
            open_review_count=len(open_reviews),
            context_sha256=_sha256_text(_stable_json(context_payload)),
            by_number=by_number,
            by_name=by_name,
            blocked_numbers=frozenset(blocked_numbers),
            blocked_names=frozenset(blocked_names),
        )

    @staticmethod
    def _source_match(
        *,
        method: str,
        item: Mapping[str, str],
    ) -> dict[str, Any]:
        return {
            "state": "source_matched_canonical_pending",
            "method": method,
            "source_taxonomy_record_id": item["source_taxonomy_record_id"],
            "world_plants_number": item["world_plants_number"] or None,
            "source_taxon_rank_code": item["taxon_rank_code"],
            "canonical_taxon_id": None,
            "candidate_source_taxonomy_ids": [item["source_taxonomy_record_id"]],
            "canonical_projection_blocker": CANONICAL_PROJECTION_BLOCKER,
        }

    @staticmethod
    def _resolve_taxon(
        context: TaxonomyReconciliationContext,
        *,
        scientific_name: str,
        accepted_name: str,
        supplied_world_plants_number: str,
    ) -> dict[str, Any]:
        lookup_name = _canonical_name(accepted_name or scientific_name)
        number_key = _canonical_identifier(supplied_world_plants_number)

        if number_key and number_key in context.blocked_numbers:
            matches = context.by_number.get(number_key, ())
            return {
                "state": "taxonomy_review_required",
                "method": "world_plants_number",
                "source_taxonomy_record_id": None,
                "world_plants_number": supplied_world_plants_number or None,
                "source_taxon_rank_code": None,
                "canonical_taxon_id": None,
                "candidate_source_taxonomy_ids": sorted(
                    item["source_taxonomy_record_id"] for item in matches
                ),
                "canonical_projection_blocker": CANONICAL_PROJECTION_BLOCKER,
            }

        if lookup_name and lookup_name in context.blocked_names:
            matches = context.by_name.get(lookup_name, ())
            return {
                "state": "taxonomy_review_required",
                "method": "scientific_name_exact",
                "source_taxonomy_record_id": None,
                "world_plants_number": None,
                "source_taxon_rank_code": None,
                "canonical_taxon_id": None,
                "candidate_source_taxonomy_ids": sorted(
                    item["source_taxonomy_record_id"] for item in matches
                ),
                "canonical_projection_blocker": CANONICAL_PROJECTION_BLOCKER,
            }

        if number_key:
            matches = context.by_number.get(number_key, ())
            if len(matches) == 1:
                return PostgresOccurrencePersistence._source_match(
                    method="world_plants_number", item=matches[0]
                )
            if len(matches) > 1:
                return {
                    "state": "ambiguous",
                    "method": "world_plants_number",
                    "source_taxonomy_record_id": None,
                    "world_plants_number": supplied_world_plants_number,
                    "source_taxon_rank_code": None,
                    "canonical_taxon_id": None,
                    "candidate_source_taxonomy_ids": sorted(
                        item["source_taxonomy_record_id"] for item in matches
                    ),
                    "canonical_projection_blocker": CANONICAL_PROJECTION_BLOCKER,
                }

        matches = context.by_name.get(lookup_name, ()) if lookup_name else ()
        if len(matches) == 1:
            return PostgresOccurrencePersistence._source_match(
                method="scientific_name_exact", item=matches[0]
            )
        if len(matches) > 1:
            return {
                "state": "ambiguous",
                "method": "scientific_name_exact",
                "source_taxonomy_record_id": None,
                "world_plants_number": None,
                "source_taxon_rank_code": None,
                "canonical_taxon_id": None,
                "candidate_source_taxonomy_ids": sorted(
                    item["source_taxonomy_record_id"] for item in matches
                ),
                "canonical_projection_blocker": CANONICAL_PROJECTION_BLOCKER,
            }
        return {
            "state": "unresolved",
            "method": "none",
            "source_taxonomy_record_id": None,
            "world_plants_number": None,
            "source_taxon_rank_code": None,
            "canonical_taxon_id": None,
            "candidate_source_taxonomy_ids": [],
            "canonical_projection_blocker": CANONICAL_PROJECTION_BLOCKER,
        }

    @staticmethod
    def _coordinate_state(
        latitude: Any,
        longitude: Any,
    ) -> tuple[float | None, float | None, str]:
        try:
            lat = None if latitude in (None, "") else float(latitude)
            lon = None if longitude in (None, "") else float(longitude)
        except (TypeError, ValueError):
            return None, None, "invalid"
        if lat is None and lon is None:
            return None, None, "missing"
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return lat, lon, "invalid"
        return lat, lon, "valid"

    def reconcile_batch(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        source: str,
        job_key: str,
        taxonomy_release_id: str,
        completed: bool = False,
    ) -> OccurrenceRunReceipt:
        source_name = source.strip().casefold()
        if source_name not in SUPPORTED_SOURCES:
            raise ValueError("UNSUPPORTED_OCCURRENCE_SOURCE")
        if not job_key.strip():
            raise ValueError("JOB_KEY_REQUIRED")
        rows = [dict(record) for record in records]
        if not rows:
            raise ValueError("OCCURRENCE_BATCH_EMPTY")
        if len(rows) > MAX_BATCH_RECORDS:
            raise ValueError("OCCURRENCE_BATCH_LIMIT_EXCEEDED")

        source_ids: set[str] = set()
        for record in rows:
            source_id = str(record.get("source_record_id") or "").strip()
            if not source_id:
                raise ValueError("SOURCE_RECORD_ID_REQUIRED")
            if source_id in source_ids:
                raise ValueError("DUPLICATE_SOURCE_RECORD_ID_IN_BATCH")
            source_ids.add(source_id)

        batch_sha = _sha256_text("".join(_stable_json(row) + "\n" for row in rows))
        context = self.taxonomy_context(taxonomy_release_id)
        run_material = {
            "source": source_name,
            "job_key": job_key.strip(),
            "input_batch_sha256": batch_sha,
            "taxonomy_context_sha256": context.context_sha256,
            "schema_version": OCCURRENCE_RECONCILIATION_SCHEMA_VERSION,
        }
        run_id = "occ-run-" + _sha256_text(_stable_json(run_material))[:24]

        with self.engine.begin() as connection:
            existing = (
                connection.execute(
                    text(
                        "SELECT input_batch_sha256, taxonomy_context_sha256, completed "
                        "FROM occurrence_pipeline.reconciliation_runs "
                        "WHERE run_id = :run_id"
                    ),
                    {"run_id": run_id},
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if (
                    str(existing["input_batch_sha256"]) != batch_sha
                    or str(existing["taxonomy_context_sha256"]) != context.context_sha256
                ):
                    raise RuntimeError("IMMUTABLE_OCCURRENCE_RUN_CONFLICT")
                counts = self._counts_with_connection(connection, run_id)
                return OccurrenceRunReceipt(
                    run_id=run_id,
                    source=source_name,
                    job_key=job_key.strip(),
                    input_batch_sha256=batch_sha,
                    taxonomy_release_id=context.release_id,
                    taxonomy_context_sha256=context.context_sha256,
                    staged_count=counts["staged"],
                    review_count=counts["review"],
                    duplicate_skipped=len(rows),
                    completed=bool(existing["completed"]),
                )

            connection.execute(
                text(
                    """
                    INSERT INTO occurrence_pipeline.reconciliation_runs (
                        run_id, source, job_key, input_batch_sha256, input_record_count,
                        taxonomy_release_id, taxonomy_source_sha256, taxonomy_review_sha256,
                        taxonomy_open_review_count, taxonomy_context_sha256, schema_version,
                        completed
                    ) VALUES (
                        :run_id, :source, :job_key, :input_batch_sha256, :input_record_count,
                        :taxonomy_release_id, :taxonomy_source_sha256, :taxonomy_review_sha256,
                        :taxonomy_open_review_count, :taxonomy_context_sha256, :schema_version,
                        :completed
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "source": source_name,
                    "job_key": job_key.strip(),
                    "input_batch_sha256": batch_sha,
                    "input_record_count": len(rows),
                    "taxonomy_release_id": context.release_id,
                    "taxonomy_source_sha256": context.source_sha256,
                    "taxonomy_review_sha256": context.review_sha256,
                    "taxonomy_open_review_count": context.open_review_count,
                    "taxonomy_context_sha256": context.context_sha256,
                    "schema_version": OCCURRENCE_RECONCILIATION_SCHEMA_VERSION,
                    "completed": completed,
                },
            )

            review_count = 0
            review_states = {"taxonomy_review_required", "ambiguous", "unresolved"}
            for record in rows:
                source_id = str(record["source_record_id"]).strip()
                scientific_name = str(record.get("scientific_name") or "").strip()
                if not scientific_name:
                    raise ValueError("SCIENTIFIC_NAME_REQUIRED")
                accepted_name = str(record.get("accepted_name") or "").strip()
                provider_taxon_key = str(
                    record.get("taxon_key") or record.get("accepted_taxon_key") or ""
                ).strip()
                supplied_number = str(record.get("world_plants_number") or "").strip()
                resolution = self._resolve_taxon(
                    context,
                    scientific_name=scientific_name,
                    accepted_name=accepted_name,
                    supplied_world_plants_number=supplied_number,
                )
                lat, lon, coordinate_state = self._coordinate_state(
                    record.get("latitude"), record.get("longitude")
                )
                try:
                    uncertainty = (
                        None
                        if record.get("coordinate_uncertainty_m") in (None, "")
                        else float(record["coordinate_uncertainty_m"])
                    )
                except (TypeError, ValueError):
                    uncertainty = None
                if uncertainty is not None and uncertainty < 0:
                    uncertainty = None

                reconciliation_state = str(resolution["state"])
                reasons: list[str] = []
                if reconciliation_state in review_states:
                    reasons.append(reconciliation_state)
                if coordinate_state == "invalid":
                    reasons.append("invalid_coordinates")

                normalized = {
                    "source": source_name,
                    "source_record_id": source_id,
                    "scientific_name": scientific_name,
                    "accepted_name": accepted_name or None,
                    "provider_taxon_key": provider_taxon_key or None,
                    "supplied_world_plants_number": supplied_number or None,
                    "source_taxonomy_record_id": resolution[
                        "source_taxonomy_record_id"
                    ],
                    "world_plants_number": resolution["world_plants_number"],
                    "source_taxon_rank_code": resolution["source_taxon_rank_code"],
                    "canonical_taxon_id": None,
                    "reconciliation_state": reconciliation_state,
                    "reconciliation_method": resolution["method"],
                    "canonical_projection_blocker": CANONICAL_PROJECTION_BLOCKER,
                    "latitude": lat,
                    "longitude": lon,
                    "coordinate_state": coordinate_state,
                    "coordinate_uncertainty_m": uncertainty,
                    "country_code": record.get("country_code"),
                    "locality": record.get("locality"),
                    "event_date": (
                        str(record.get("event_date"))
                        if record.get("event_date") is not None
                        else None
                    ),
                    "recorded_by": record.get("recorded_by"),
                    "license": record.get("license"),
                    "basis_of_record": record.get("basis_of_record"),
                    "taxonomy_release_id": context.release_id,
                    "taxonomy_context_sha256": context.context_sha256,
                }
                connection.execute(
                    text(
                        """
                        INSERT INTO occurrence_pipeline.staged_occurrences (
                            run_id, source_record_id, scientific_name, accepted_name,
                            provider_taxon_key, supplied_world_plants_number,
                            source_taxonomy_record_id, world_plants_number,
                            source_taxon_rank_code, canonical_taxon_id,
                            reconciliation_state, reconciliation_method,
                            canonical_projection_blocker, latitude, longitude,
                            coordinate_uncertainty_m, country_code, locality, event_date,
                            recorded_by, license, basis_of_record, raw_sha256,
                            raw_payload, normalized_payload
                        ) VALUES (
                            :run_id, :source_record_id, :scientific_name, :accepted_name,
                            :provider_taxon_key, :supplied_world_plants_number,
                            :source_taxonomy_record_id, :world_plants_number,
                            :source_taxon_rank_code, :canonical_taxon_id,
                            :reconciliation_state, :reconciliation_method,
                            :canonical_projection_blocker, :latitude, :longitude,
                            :coordinate_uncertainty_m, :country_code, :locality, :event_date,
                            :recorded_by, :license, :basis_of_record, :raw_sha256,
                            CAST(:raw_payload AS jsonb), CAST(:normalized_payload AS jsonb)
                        )
                        """
                    ),
                    {
                        **normalized,
                        "run_id": run_id,
                        "raw_sha256": _raw_sha(record),
                        "raw_payload": _stable_json(record),
                        "normalized_payload": _stable_json(normalized),
                    },
                )
                for reason in reasons:
                    connection.execute(
                        text(
                            """
                            INSERT INTO occurrence_pipeline.review_queue (
                                run_id, source_record_id, scientific_name, reason,
                                reconciliation_state, candidate_source_taxonomy_ids
                            ) VALUES (
                                :run_id, :source_record_id, :scientific_name, :reason,
                                :reconciliation_state,
                                CAST(:candidate_source_taxonomy_ids AS jsonb)
                            )
                            """
                        ),
                        {
                            "run_id": run_id,
                            "source_record_id": source_id,
                            "scientific_name": scientific_name,
                            "reason": reason,
                            "reconciliation_state": reconciliation_state,
                            "candidate_source_taxonomy_ids": _stable_json(
                                resolution["candidate_source_taxonomy_ids"]
                            ),
                        },
                    )
                    review_count += 1

            connection.execute(
                text(
                    """
                    INSERT INTO occurrence_pipeline.checkpoints (
                        run_id, next_record_index, staged_count, review_count,
                        duplicate_skipped, completed
                    ) VALUES (
                        :run_id, :next_record_index, :staged_count, :review_count,
                        0, :completed
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "next_record_index": len(rows),
                    "staged_count": len(rows),
                    "review_count": review_count,
                    "completed": completed,
                },
            )

        return OccurrenceRunReceipt(
            run_id=run_id,
            source=source_name,
            job_key=job_key.strip(),
            input_batch_sha256=batch_sha,
            taxonomy_release_id=context.release_id,
            taxonomy_context_sha256=context.context_sha256,
            staged_count=len(rows),
            review_count=review_count,
            duplicate_skipped=0,
            completed=completed,
        )

    @staticmethod
    def _counts_with_connection(connection: Any, run_id: str) -> dict[str, int]:
        staged = connection.execute(
            text(
                "SELECT count(*) FROM occurrence_pipeline.staged_occurrences "
                "WHERE run_id = :run_id"
            ),
            {"run_id": run_id},
        ).scalar_one()
        review = connection.execute(
            text(
                "SELECT count(*) FROM occurrence_pipeline.review_queue "
                "WHERE run_id = :run_id AND status = 'open'"
            ),
            {"run_id": run_id},
        ).scalar_one()
        return {"staged": int(staged), "review": int(review)}

    def run_status(self, run_id: str) -> dict[str, Any]:
        with self.engine.connect() as connection:
            run = (
                connection.execute(
                    text(
                        "SELECT run_id, source, job_key, input_batch_sha256, "
                        "input_record_count, taxonomy_release_id, taxonomy_source_sha256, "
                        "taxonomy_review_sha256, taxonomy_open_review_count, "
                        "taxonomy_context_sha256, schema_version, completed, "
                        "automatic_promotion, created_at, updated_at "
                        "FROM occurrence_pipeline.reconciliation_runs "
                        "WHERE run_id = :run_id"
                    ),
                    {"run_id": run_id},
                )
                .mappings()
                .first()
            )
            if run is None:
                raise LookupError("OCCURRENCE_RUN_NOT_FOUND")
            counts = self._counts_with_connection(connection, run_id)
        return {
            **dict(run),
            "created_at": run["created_at"].isoformat(),
            "updated_at": run["updated_at"].isoformat(),
            "staged_count": counts["staged"],
            "open_review_count": counts["review"],
            "canonical_projection_ready": False,
            "canonical_projection_blocker": CANONICAL_PROJECTION_BLOCKER,
            "ready_for_production_graph_mutation": False,
            "taxonomy_activation_authorized": False,
            "publication_authorized": False,
        }
