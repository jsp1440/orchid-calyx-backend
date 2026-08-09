from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL test URL required")


def _apply(engine, filename: str) -> None:
    sql = (Path(__file__).parents[1] / "migrations" / filename).read_text(encoding="utf-8")
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)


def _fresh_engine():
    engine = create_engine(DATABASE_URL)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS occurrence_pipeline CASCADE")
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS taxonomy_pipeline CASCADE")
    for migration in (
        "107_world_plants_release_staging.sql",
        "108_occurrence_reconciliation_runs.sql",
        "109_occurrence_taxonomy_context_guard.sql",
    ):
        _apply(engine, migration)
    return engine


def _seed_release(engine, *, state: str, completed: bool) -> str:
    release_id = "c" * 64
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO taxonomy_pipeline.releases (
                    release_id, source_sha256, version_label, filename, acquired_at,
                    source_encoding, source_row_count, source_payload, state
                ) VALUES (
                    :release_id, :release_id, 'WorldOrchids 26-08', 'fixture.csv',
                    '2026-08-08T00:00:00Z', 'latin-1', 1, :payload, :state
                )
                """
            ),
            {"release_id": release_id, "payload": b"fixture", "state": state},
        )
        connection.execute(
            text(
                """
                INSERT INTO taxonomy_pipeline.staging_checkpoints (
                    release_id, next_row_index, staged_count, completed
                ) VALUES (:release_id, 1, 1, :completed)
                """
            ),
            {"release_id": release_id, "completed": completed},
        )
    return release_id


def _insert_run(engine, release_id: str, *, source_sha: str | None = None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO occurrence_pipeline.reconciliation_runs (
                    run_id, source, job_key, input_batch_sha256, input_record_count,
                    taxonomy_release_id, taxonomy_source_sha256, taxonomy_review_sha256,
                    taxonomy_open_review_count, taxonomy_context_sha256, schema_version
                ) VALUES (
                    'run-1', 'gbif', 'job-1', :input_sha, 1,
                    :release_id, :source_sha, :review_sha, 0, :context_sha, '2.0.0'
                )
                """
            ),
            {
                "input_sha": "1" * 64,
                "release_id": release_id,
                "source_sha": source_sha or release_id,
                "review_sha": "2" * 64,
                "context_sha": "3" * 64,
            },
        )


def test_guard_rejects_incomplete_taxonomy_checkpoint() -> None:
    engine = _fresh_engine()
    try:
        release_id = _seed_release(engine, state="staging", completed=False)
        with pytest.raises(DBAPIError, match="TAXONOMY_RELEASE_NOT_READY|TAXONOMY_STAGING_INCOMPLETE"):
            _insert_run(engine, release_id)
    finally:
        engine.dispose()


def test_guard_accepts_completed_review_required_taxonomy() -> None:
    engine = _fresh_engine()
    try:
        release_id = _seed_release(engine, state="review_required", completed=True)
        _insert_run(engine, release_id)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM occurrence_pipeline.reconciliation_runs")).scalar_one() == 1
    finally:
        engine.dispose()


def test_guard_rejects_source_sha_mismatch() -> None:
    engine = _fresh_engine()
    try:
        release_id = _seed_release(engine, state="staged", completed=True)
        with pytest.raises(DBAPIError, match="TAXONOMY_SOURCE_SHA_MISMATCH"):
            _insert_run(engine, release_id, source_sha="d" * 64)
    finally:
        engine.dispose()
