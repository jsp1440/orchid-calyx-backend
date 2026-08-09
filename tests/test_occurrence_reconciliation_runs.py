from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from runtime.occurrence_persistence import PostgresOccurrencePersistence

DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL test URL required")


def _apply(engine, filename: str) -> None:
    sql = (Path(__file__).parents[1] / "migrations" / filename).read_text(encoding="utf-8")
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)


@pytest.fixture()
def engine():
    instance = create_engine(DATABASE_URL)
    with instance.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS occurrence_pipeline CASCADE")
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS taxonomy_pipeline CASCADE")
    _apply(instance, "107_world_plants_release_staging.sql")
    _apply(instance, "108_occurrence_reconciliation_runs.sql")
    yield instance
    instance.dispose()


def _seed_taxonomy(engine, release_id: str = "a" * 64) -> str:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO taxonomy_pipeline.releases (
                    release_id, source_sha256, version_label, filename, acquired_at,
                    source_encoding, source_row_count, source_payload, state
                ) VALUES (
                    :release_id, :release_id, 'WorldOrchids 26-08', 'fixture.csv',
                    '2026-08-08T00:00:00Z', 'latin-1', 2, :payload, 'staged'
                )
                """
            ),
            {"release_id": release_id, "payload": b"fixture"},
        )
        for row_number, code, name in (
            (1, "WP-1", "Laelia anceps"),
            (2, "WP-2", "Cattleya mossiae"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO taxonomy_pipeline.staged_taxa (
                        release_id, source_row_number, taxon_code, scientific_name,
                        row_checksum, normalized_payload
                    ) VALUES (
                        :release_id, :row_number, :code, :name, :checksum,
                        CAST(:payload AS jsonb)
                    )
                    """
                ),
                {
                    "release_id": release_id,
                    "row_number": row_number,
                    "code": code,
                    "name": name,
                    "checksum": f"{row_number:064x}",
                    "payload": f'{{"taxon_code":"{code}","name":"{name}"}}',
                },
            )
    return release_id


def _records() -> list[dict[str, object]]:
    return [
        {
            "source_record_id": "gbif-1",
            "scientific_name": "Laelia anceps",
            "taxon_key": "WP-1",
            "latitude": 19.4,
            "longitude": -99.1,
            "coordinate_uncertainty_m": 25,
            "license": "CC_BY",
            "raw": {"provider": "gbif", "key": 1},
        },
        {
            "source_record_id": "gbif-2",
            "scientific_name": "Cattleya mossiae",
            "latitude": 10.1,
            "longitude": -66.9,
            "license": "CC0",
            "raw": {"provider": "gbif", "key": 2},
        },
    ]


def test_exact_replay_is_idempotent_and_preserves_taxonomy_binding(engine) -> None:
    release_id = _seed_taxonomy(engine)
    store = PostgresOccurrencePersistence(engine)

    first = store.reconcile_batch(
        _records(), source="gbif", job_key="bounded-001", taxonomy_release_id=release_id
    )
    replay = store.reconcile_batch(
        _records(), source="gbif", job_key="bounded-001", taxonomy_release_id=release_id
    )

    assert first.run_id == replay.run_id
    assert first.taxonomy_context_sha256 == replay.taxonomy_context_sha256
    assert first.staged_count == 2
    assert first.review_count == 0
    assert replay.staged_count == 2
    assert replay.duplicate_skipped == 2
    status = store.run_status(first.run_id)
    assert status["taxonomy_release_id"] == release_id
    assert status["ready_for_production_graph_mutation"] is False
    assert status["taxonomy_activation_authorized"] is False


def test_taxonomy_review_change_creates_new_run_and_preserves_old_evidence(engine) -> None:
    release_id = _seed_taxonomy(engine)
    store = PostgresOccurrencePersistence(engine)
    first = store.reconcile_batch(
        _records(), source="gbif", job_key="bounded-001", taxonomy_release_id=release_id
    )

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO taxonomy_pipeline.review_queue (
                    release_id, review_key, category, summary, evidence
                ) VALUES (
                    :release_id, 'duplicate:WP-1:Laelia anceps', 'duplicate_identity',
                    'review Laelia identity',
                    '{"taxon_code":"WP-1","name":"Laelia anceps"}'::jsonb
                )
                """
            ),
            {"release_id": release_id},
        )

    second = store.reconcile_batch(
        _records(), source="gbif", job_key="bounded-001", taxonomy_release_id=release_id
    )
    assert second.run_id != first.run_id
    assert second.taxonomy_context_sha256 != first.taxonomy_context_sha256
    assert second.review_count == 1

    with engine.connect() as connection:
        old_state = connection.execute(
            text(
                "SELECT reconciliation_state FROM occurrence_pipeline.staged_occurrences "
                "WHERE run_id = :run_id AND source_record_id = 'gbif-1'"
            ),
            {"run_id": first.run_id},
        ).scalar_one()
        new_state = connection.execute(
            text(
                "SELECT reconciliation_state FROM occurrence_pipeline.staged_occurrences "
                "WHERE run_id = :run_id AND source_record_id = 'gbif-1'"
            ),
            {"run_id": second.run_id},
        ).scalar_one()
    assert old_state == "resolved"
    assert new_state == "taxonomy_review_required"


def test_resolved_taxonomy_review_changes_context_without_blocking_match(engine) -> None:
    release_id = _seed_taxonomy(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO taxonomy_pipeline.review_queue (
                    release_id, review_key, category, summary, evidence, status
                ) VALUES (
                    :release_id, 'accepted-name:1', 'accepted_name_change',
                    'resolved rename review',
                    '{"before":"Schomburgkia anceps","after":"Laelia anceps"}'::jsonb,
                    'resolved'
                )
                """
            ),
            {"release_id": release_id},
        )
    store = PostgresOccurrencePersistence(engine)
    receipt = store.reconcile_batch(
        _records(), source="gbif", job_key="bounded-001", taxonomy_release_id=release_id
    )
    assert receipt.review_count == 0


def test_invalid_coordinates_enter_review_without_losing_taxon_resolution(engine) -> None:
    release_id = _seed_taxonomy(engine)
    store = PostgresOccurrencePersistence(engine)
    records = [_records()[0] | {"latitude": 999, "longitude": -99.1}]
    receipt = store.reconcile_batch(
        records, source="gbif", job_key="bounded-coordinates", taxonomy_release_id=release_id
    )
    assert receipt.review_count == 1
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT reconciliation_state, normalized_payload FROM occurrence_pipeline.staged_occurrences "
                "WHERE run_id = :run_id"
            ),
            {"run_id": receipt.run_id},
        ).mappings().one()
    assert row["reconciliation_state"] == "resolved"
    assert row["normalized_payload"]["coordinate_state"] == "invalid"


def test_run_identity_is_bound_to_taxonomy_release(engine) -> None:
    first_release = _seed_taxonomy(engine, "a" * 64)
    second_release = _seed_taxonomy(engine, "b" * 64)
    store = PostgresOccurrencePersistence(engine)
    first = store.reconcile_batch(
        _records(), source="gbif", job_key="bounded-001", taxonomy_release_id=first_release
    )
    second = store.reconcile_batch(
        _records(), source="gbif", job_key="bounded-001", taxonomy_release_id=second_release
    )
    assert first.run_id != second.run_id
    assert first.taxonomy_release_id != second.taxonomy_release_id
    assert first.taxonomy_context_sha256 != second.taxonomy_context_sha256
