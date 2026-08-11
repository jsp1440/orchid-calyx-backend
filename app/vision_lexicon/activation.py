"""Fail-closed durable activation for the Vision-Lexicon bridge.

This module deliberately does not connect to PostgreSQL at import time. It
selects the repository from explicit runtime configuration and verifies the
``oc_vision`` schema before durable writes are allowed. Schema activation and
durable-write enablement are intentionally reported as separate states.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.database import get_database_url

from .contracts import (
    CharacterConformanceCheck,
    CharacterConformanceResult,
    FigureSpecification,
    FigureValidationRun,
    MediaType,
    ValidationRunStatus,
    VisionReviewState,
)
from .persistence import MemoryVisionLexiconRepository, PostgresVisionLexiconRepository
from .service import VisionLexiconService, vision_lexicon_capability_status

_DURABLE_FLAG = "CALYX_VISION_DURABLE_ENABLED"
_EPHEMERAL_FLAG = "CALYX_VISION_EPHEMERAL_WRITES_ENABLED"
_REQUIRED_TABLES = (
    "reference_image_sets",
    "vision_analyses",
    "figure_specifications",
    "figure_validation_runs",
    "vision_review_records",
)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def durable_requested() -> bool:
    return _truthy(os.getenv(_DURABLE_FLAG))


def _production_runtime() -> bool:
    env = (os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "").strip().lower()
    return env in {"prod", "production"} or _truthy(os.getenv("RENDER"))


def ephemeral_writes_allowed() -> bool:
    """Permit memory writes for tests/dev, never silently on production."""
    if durable_requested():
        return False
    if _production_runtime():
        return _truthy(os.getenv(_EPHEMERAL_FLAG))
    return True


def _postgres_url() -> str:
    url = get_database_url()
    if not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("VISION_POSTGRES_REQUIRED")
    return url


def schema_ready() -> bool:
    """Report whether the governed Vision schema exists, independent of writes.

    A migration may be safely applied before durable writes are enabled. The
    status endpoint must therefore be able to report ``migration_activated``
    truthfully while ``CALYX_VISION_DURABLE_ENABLED`` remains false.
    """

    try:
        with psycopg.connect(_postgres_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT to_regnamespace('oc_vision') IS NOT NULL")
            if not bool(cur.fetchone()[0]):
                return False
            for table in _REQUIRED_TABLES:
                cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"oc_vision.{table}",))
                if not bool(cur.fetchone()[0]):
                    return False
        return True
    except Exception:
        return False


def _guarded_connection() -> Any:
    if not durable_requested():
        raise RuntimeError("VISION_DURABLE_PERSISTENCE_DISABLED")
    conn = psycopg.connect(_postgres_url())
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regnamespace('oc_vision') IS NOT NULL")
            if not bool(cur.fetchone()[0]):
                raise RuntimeError("VISION_SCHEMA_NOT_ACTIVATED")
            for table in _REQUIRED_TABLES:
                cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"oc_vision.{table}",))
                if not bool(cur.fetchone()[0]):
                    raise RuntimeError(f"VISION_SCHEMA_TABLE_MISSING:{table}")
        return conn
    except Exception:
        conn.close()
        raise


class HardenedPostgresVisionLexiconRepository(PostgresVisionLexiconRepository):
    """Schema-safe overrides for figure and validation persistence."""

    _FIGURE_COLUMNS = """
        figure_spec_id, target_concept_id, purpose, scope, taxon_scope,
        reference_set_ids, required_structures, required_character_states,
        required_relationships, allowed_variation, excluded_interpretations,
        relative_geometry_constraints, color_constraints, literature_constraints,
        label_requirements, uncertainty_notes, generation_notes, media_type,
        temporal_sequence, required_stage_order, motion_constraints, duration_range,
        loop_behavior, scientific_state_transitions, reduced_motion_alternative,
        created_by, review_state, version, provenance
    """

    def save_figure_spec(self, spec: FigureSpecification) -> FigureSpecification:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO oc_vision.figure_specifications ({self._FIGURE_COLUMNS})
                VALUES (
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                )
                ON CONFLICT (figure_spec_id) DO NOTHING
                """,
                (
                    spec.figure_spec_id,
                    spec.target_concept_id,
                    spec.purpose,
                    spec.scope,
                    spec.taxon_scope,
                    list(spec.reference_set_ids),
                    Jsonb(spec.required_structures),
                    Jsonb(spec.required_character_states),
                    Jsonb(spec.required_relationships),
                    Jsonb(spec.allowed_variation),
                    Jsonb(spec.excluded_interpretations),
                    Jsonb(spec.relative_geometry_constraints),
                    Jsonb(spec.color_constraints),
                    Jsonb(spec.literature_constraints),
                    Jsonb(spec.label_requirements),
                    spec.uncertainty_notes,
                    spec.generation_notes,
                    spec.media_type,
                    Jsonb(spec.temporal_sequence) if spec.temporal_sequence is not None else None,
                    Jsonb(spec.required_stage_order) if spec.required_stage_order is not None else None,
                    Jsonb(spec.motion_constraints) if spec.motion_constraints is not None else None,
                    Jsonb(spec.duration_range) if spec.duration_range is not None else None,
                    spec.loop_behavior,
                    Jsonb(spec.scientific_state_transitions)
                    if spec.scientific_state_transitions is not None
                    else None,
                    spec.reduced_motion_alternative,
                    spec.created_by,
                    spec.review_state,
                    spec.version,
                    Jsonb(spec.provenance),
                ),
            )
        return spec

    def get_figure_spec(self, figure_spec_id: Any) -> FigureSpecification | None:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._FIGURE_COLUMNS} FROM oc_vision.figure_specifications "
                "WHERE figure_spec_id=%s",
                (figure_spec_id,),
            )
            row = cur.fetchone()
        return self._build_figure_spec_explicit(row) if row else None

    def list_figure_specs_for_concept(self, concept_id: Any) -> list[FigureSpecification]:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {self._FIGURE_COLUMNS} FROM oc_vision.figure_specifications "
                "WHERE target_concept_id=%s",
                (concept_id,),
            )
            return [self._build_figure_spec_explicit(row) for row in cur.fetchall()]

    @staticmethod
    def _build_figure_spec_explicit(row: Any) -> FigureSpecification:
        return FigureSpecification(
            figure_spec_id=row[0],
            target_concept_id=row[1],
            purpose=row[2],
            scope=row[3],
            taxon_scope=row[4],
            reference_set_ids=tuple(row[5] or ()),
            required_structures=row[6] or [],
            required_character_states=row[7] or [],
            required_relationships=row[8] or [],
            allowed_variation=row[9] or {},
            excluded_interpretations=row[10] or [],
            relative_geometry_constraints=row[11] or {},
            color_constraints=row[12] or {},
            literature_constraints=row[13] or [],
            label_requirements=row[14] or [],
            uncertainty_notes=row[15],
            generation_notes=row[16],
            media_type=MediaType(row[17]),
            temporal_sequence=row[18],
            required_stage_order=row[19],
            motion_constraints=row[20],
            duration_range=row[21],
            loop_behavior=row[22],
            scientific_state_transitions=row[23],
            reduced_motion_alternative=row[24],
            created_by=row[25],
            review_state=VisionReviewState(row[26]),
            version=row[27],
            provenance=row[28] or {},
        )

    def get_validation_run(self, validation_run_id: Any) -> FigureValidationRun | None:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT validation_run_id, asset_id, figure_spec_id, vision_analysis_id,
                       status, overall_review_state, provenance
                FROM oc_vision.figure_validation_runs
                WHERE validation_run_id=%s
                """,
                (validation_run_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                """
                SELECT check_id, validation_run_id, character_id,
                       expected_state_or_range, observed_state_or_value,
                       result, confidence, notes, review_state
                FROM oc_vision.character_conformance_checks
                WHERE validation_run_id=%s
                """,
                (validation_run_id,),
            )
            check_rows = cur.fetchall()
        checks = tuple(
            CharacterConformanceCheck(
                check_id=c[0],
                validation_run_id=c[1],
                character_id=c[2],
                expected_state_or_range=c[3],
                observed_state_or_value=c[4],
                result=CharacterConformanceResult(c[5]),
                confidence=float(c[6]) if c[6] is not None else None,
                notes=c[7],
                review_state=VisionReviewState(c[8]),
            )
            for c in check_rows
        )
        return FigureValidationRun(
            validation_run_id=row[0],
            asset_id=row[1],
            figure_spec_id=row[2],
            vision_analysis_id=row[3],
            status=ValidationRunStatus(row[4]),
            overall_review_state=VisionReviewState(row[5]),
            provenance=row[6] or {},
            conformance_checks=checks,
        )


def build_vision_lexicon_service() -> VisionLexiconService:
    if durable_requested():
        return VisionLexiconService(HardenedPostgresVisionLexiconRepository(_guarded_connection))
    return VisionLexiconService(MemoryVisionLexiconRepository())


def capability_status() -> dict[str, Any]:
    base = vision_lexicon_capability_status()
    ready = schema_ready()
    durable = durable_requested()
    base["persistence_mode"] = "postgres" if durable else "memory"
    base["durable_persistence_enabled"] = durable
    base["schema_ready"] = ready
    base["migration_activated"] = ready
    base["live_inference_enabled"] = False
    if durable and not ready:
        base["provider_status"] = "PERSISTENCE_NOT_READY"
    return base
