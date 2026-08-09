from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from runtime.occurrence_persistence import (
    CANONICAL_PROJECTION_BLOCKER,
    PostgresOccurrencePersistence,
)

DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="PostgreSQL test URL required")


def _apply(engine, filename: str) -> None:
    sql = (Path(__file__).parents[1] / "migrations" / filename).read_text(
        encoding="utf-8"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)


@pytest.fixture()
def engine():
    instance = create_engine(DATABASE_URL)
    with instance.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS occurrence_pipeline CASCADE")
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS taxonomy_pipeline CASCADE")
    for migration in (
        "107_world_plants_release_staging.sql",
        "108_occurrence_reconciliation_runs.sql",
        "109_occurrence_taxonomy_context_guard.sql",
    ):
        _apply(instance, migration)
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
        connection.execute(
            text(
                """
                INSERT INTO taxonomy_pipeline.staging_checkpoints (
                    release_id, next_row_index, staged_count, completed
                ) VALUES (:release_id, 2, 2, true)
                """
            ),
            {"release_id": release_id},
        )
        for row_number, rank_code, number, name in (
            (1, "S", "WP-1", "Laelia anceps"),
            (2, "S", "WP-2", "Cattleya mossiae"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO taxonomy_pipeline.staged_taxa (
                        release_id, source_row_number, taxon_code, world_plants_number,
                        scientific_name, row_checksum, normalized_payload
                    ) VALUES (
                        :release_id, :row_number, :rank_code, :number, :name,
                        :checksum, CAST(:payload AS jsonb)
                    )
                    """
                ),
                {
                    "release_id": release_id,
                    "row_number": row_number,
                    "rank_code": rank_code,
                    "number": number,
                    "name": name,
                    "checksum": f"{row_number:064x}",
                    "payload": (
                        f'{{"taxon_code":"{rank_code}",'
                        f'"world_plants_number":"{number}","name":"{name}"}}'
                    ),
                },
            )
    return release_id


def _records() -> list[dict[str, object]]:
    return [
        {
            "source_record_id": "gbif-1",
            "scientific_name": "Laelia anceps",
            "taxon_key": "GBIF-999",
            "world_plants_number": "WP-1",
            "latitude": 19.4,
            "longitude": -99.1,
            "coordinate_uncertainty_m": 25,
            "license": "CC_BY",
            "raw": {"provider": "gbif", "key": 1},
        },
        {
            "source_record_id": "gbif-2",
            "scientific_name": "Cattleya mossiae",
            "taxon_key": "GBIF-1000",
            "latitude": 10.1,
            "longitude": -66.9,
            "license": "CC0",
            "raw": {"provider": "gbif", "key": 2},
        },
    ]


def test_exact_replay_preserves_source_taxonomy_without_inventing_canonical_id(
    engine,
) -> None:
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
    assert first.canonical_projection_ready is False
    assert first.canonical_projection_blocker == CANONICAL_PROJECTION_BLOCKER

    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    "SELECT source_record_id, provider_taxon_key, world_plants_number, "
                    "source_taxonomy_record_id, canonical_taxon_id, reconciliation_state, "
                    "reconciliation_method FROM occurrence_pipeline.staged_occurrences "
                    "WHERE run_id = :run_id ORDER BY source_record_id"
                ),
                {"run_id": first.run_id},
            )
            .mappings()
            .all()
        )
    assert rows[0]["provider_taxon_key"] == "GBIF-999"
    assert rows[0]["world_plants_number"] == "WP-1"
    assert rows[0]["source_taxonomy_record_id"].endswith(":row:1")
    assert rows[0]["reconciliation_method"] == "world_plants_number"
    assert rows[1]["reconciliation_method"] == "scientific_name_exact"
    assert all(row["canonical_taxon_id"] is None for row in rows)
    assert all(
        row["reconciliation_state"] == "source_matched_canonical_pending"
        for row in rows
    )


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
                    :release_id, 'duplicate:S:Laelia anceps', 'duplicate_identity',
                    'review Laelia identity',
                    '{"taxon_code":"S","name":"Laelia anceps"}'::jsonb
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
    assert old_state == "source_matched_canonical_pending"
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


def test_invalid_coordinates_enter_review_without_losing_source_taxonomy_match(
    engine,
) -> None:
    release_id = _seed_taxonomy(engine)
    store = PostgresOccurrencePersistence(engine)
    records = [_records()[0] | {"latitude": 999, "longitude": -99.1}]
    receipt = store.reconcile_batch(
        records, source="gbif", job_key="bounded-coordinates", taxonomy_release_id=release_id
    )
    assert receipt.review_count == 1
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT reconciliation_state, canonical_taxon_id, normalized_payload "
                    "FROM occurrence_pipeline.staged_occurrences WHERE run_id = :run_id"
                ),
                {"run_id": receipt.run_id},
            )
            .mappings()
            .one()
        )
    assert row["reconciliation_state"] == "source_matched_canonical_pending"
    assert row["canonical_taxon_id"] is None
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


def test_rank_code_is_never_used_as_taxon_identity(engine) -> None:
    release_id = _seed_taxonomy(engine)
    store = PostgresOccurrencePersistence(engine)
    receipt = store.reconcile_batch(
        _records(), source="gbif", job_key="rank-safety", taxonomy_release_id=release_id
    )
    with engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    "SELECT source_taxon_rank_code, source_taxonomy_record_id, "
                    "canonical_taxon_id FROM occurrence_pipeline.staged_occurrences "
                    "WHERE run_id = :run_id ORDER BY source_record_id"
                ),
                {"run_id": receipt.run_id},
            )
            .mappings()
            .all()
        )
    assert {row["source_taxon_rank_code"] for row in rows} == {"S"}
    assert all(row["source_taxonomy_record_id"] != "S" for row in rows)
    assert all(row["canonical_taxon_id"] is None for row in rows)
