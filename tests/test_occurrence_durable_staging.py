from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from runtime.occurrence_persistence import (
    PostgresOccurrenceStagingStore,
    stage_and_persist_occurrences,
)

ROOT = Path(__file__).parents[1]

pytestmark = pytest.mark.skipif(
    not os.getenv("OCCURRENCE_STAGING_TEST_DATABASE_URL"),
    reason="OCCURRENCE_STAGING_TEST_DATABASE_URL not configured",
)


@pytest.fixture
def engine():
    engine = create_engine(os.environ["OCCURRENCE_STAGING_TEST_DATABASE_URL"])
    migration = (ROOT / "migrations/106_occurrence_staging_runtime.sql").read_text()
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS occurrence_pipeline CASCADE"))
        connection.exec_driver_sql(migration)
    yield engine
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS occurrence_pipeline CASCADE"))
    engine.dispose()


def _records():
    return [
        {
            "source": "gbif",
            "source_record_id": "gbif-1",
            "scientific_name": "Cattleya labiata",
            "accepted_name": "Cattleya labiata",
            "taxon_key": "123",
            "latitude": -12.5,
            "longitude": -42.25,
            "country_code": "BR",
            "event_date": "2026-01-02",
            "license": "CC_BY",
            "raw": {"key": 1, "scientificName": "Cattleya labiata"},
        },
        {
            "source": "gbif",
            "source_record_id": "gbif-2",
            "scientific_name": "Unresolved orchid",
            "accepted_name": "Unresolved orchid",
            "taxon_key": "999",
            "country_code": "BR",
            "license": "CC0",
            "raw": {"key": 2, "scientificName": "Unresolved orchid"},
        },
    ]


def test_migration_is_additive_and_scoped():
    sql = (ROOT / "migrations/106_occurrence_staging_runtime.sql").read_text().lower()
    assert "create schema if not exists occurrence_pipeline" in sql
    assert sql.count("create table if not exists occurrence_pipeline.") == 3
    assert "drop table" not in sql
    assert "truncate" not in sql
    assert "oc_graph" not in sql


def test_durable_staging_persists_raw_normalized_checkpoint_and_review(engine):
    store = PostgresOccurrenceStagingStore(engine)
    result, receipt = stage_and_persist_occurrences(
        _records(),
        source="gbif",
        store=store,
        job_key="bounded-demo",
        canonical_lookup={"Cattleya labiata": "taxon:cattleya-labiata"},
    )

    assert len(result.staged) == 2
    assert result.staged[0].canonical_taxon_id == "taxon:cattleya-labiata"
    assert result.staged[0].reconciliation_state == "resolved"
    assert result.staged[1].canonical_taxon_id is None
    assert result.staged[1].reconciliation_state == "unresolved"
    assert len(result.review_queue) == 1
    assert receipt.staged_upserts == 2
    assert receipt.review_upserts == 1
    assert receipt.no_production_graph_mutation is True
    assert store.counts("gbif") == {"staged": 2, "open_review": 1}

    checkpoint = store.load_checkpoint("gbif", "bounded-demo")
    assert checkpoint is not None
    assert checkpoint["batch_start"] == 0
    assert checkpoint["batch_end"] == 2

    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT canonical_taxon_id, reconciliation_state, raw_payload, normalized_payload "
                "FROM occurrence_pipeline.staged_occurrences "
                "WHERE source='gbif' AND source_record_id='gbif-1'"
            )
        ).mappings().one()
    assert row["canonical_taxon_id"] == "taxon:cattleya-labiata"
    assert row["reconciliation_state"] == "resolved"
    assert row["raw_payload"]["key"] == 1
    assert row["normalized_payload"]["scientific_name"] == "Cattleya labiata"


def test_replay_from_new_store_instance_has_zero_duplicate_deltas(engine):
    first_store = PostgresOccurrenceStagingStore(engine)
    first, _ = stage_and_persist_occurrences(
        _records(),
        source="gbif",
        store=first_store,
        job_key="replay-demo",
        canonical_lookup={"Cattleya labiata": "taxon:cattleya-labiata"},
        batch_start=0,
    )
    assert len(first.staged) == 2

    restarted_store = PostgresOccurrenceStagingStore(engine)
    replay, receipt = stage_and_persist_occurrences(
        _records(),
        source="gbif",
        store=restarted_store,
        job_key="replay-demo",
        canonical_lookup={"Cattleya labiata": "taxon:cattleya-labiata"},
        batch_start=0,
    )

    assert replay.idempotent is True
    assert len(replay.staged) == 0
    assert replay.duplicate_skipped == 2
    assert receipt.staged_upserts == 0
    assert restarted_store.counts("gbif") == {"staged": 2, "open_review": 1}
    checkpoint = restarted_store.load_checkpoint("gbif", "replay-demo")
    assert checkpoint is not None
    assert checkpoint["batch_end"] == 2


def test_default_batch_start_resumes_from_durable_checkpoint(engine):
    store = PostgresOccurrenceStagingStore(engine)
    stage_and_persist_occurrences(
        _records()[:1],
        source="gbif",
        store=store,
        job_key="resume-demo",
        canonical_lookup={"Cattleya labiata": "taxon:cattleya-labiata"},
    )

    second, _ = stage_and_persist_occurrences(
        _records()[1:],
        source="gbif",
        store=PostgresOccurrenceStagingStore(engine),
        job_key="resume-demo",
        canonical_lookup={"Cattleya labiata": "taxon:cattleya-labiata"},
    )

    assert second.batch_start == 1
    assert second.batch_end == 2
    assert store.counts("gbif") == {"staged": 2, "open_review": 1}
