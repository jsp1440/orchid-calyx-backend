from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from runtime.world_plants_durable_intake import PostgresWorldPlantsIntakeStore

TEST_DATABASE_URL = os.getenv("WORLD_PLANTS_STAGING_TEST_DATABASE_URL")


def _release() -> bytes:
    header = "Taxon|Number|Name|Literature|TrivialName|Distribution|Synonyms|Status|Remarks|ConservationStatus|Photo|Orientation|Author"
    fields = [
        "S",
        "",
        "Cattleya labiata Lindl.",
        "literature",
        "",
        "Brazil",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
        "",
    ]
    return (header + "\n" + "|".join(fields) + "\n").encode("latin-1")


@pytest.fixture()
def store():
    if not TEST_DATABASE_URL:
        pytest.skip("WORLD_PLANTS_STAGING_TEST_DATABASE_URL is not configured")
    engine = create_engine(TEST_DATABASE_URL)
    migration = Path("migrations/107_world_plants_release_staging.sql").read_text(
        encoding="utf-8"
    )
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS taxonomy_pipeline CASCADE"))
        connection.exec_driver_sql(migration)
    yield PostgresWorldPlantsIntakeStore(engine)
    engine.dispose()


def test_durable_intake_preserves_source_and_api_report_contract(store):
    payload = _release()
    report = store.inspect_and_store(
        payload,
        filename="WorldOrchids 26-08 (Aug 2 2026).csv",
        version_label="26-08",
        acquired_at="2026-08-02",
        notes="real-contract test",
    )

    release_id = report["release_id"]
    assert report["durable_storage"] == "postgresql"
    assert report["snapshot"]["filename"] == "WorldOrchids 26-08 (Aug 2 2026).csv"
    assert report["snapshot"]["row_count"] == 1
    assert report["automatic_promotion"] is False
    assert store.source_bytes(release_id) == payload

    listed = store.list_reports()
    assert [item["release_id"] for item in listed] == [release_id]
    assert store.get(release_id)["snapshot"]["sha256"] == release_id


def test_durable_intake_stages_bounded_batch_without_local_store(store):
    report = store.inspect_and_store(
        _release(),
        filename="WorldOrchids 26-08 (Aug 2 2026).csv",
        version_label="26-08",
        acquired_at="2026-08-02",
    )
    release_id = report["release_id"]

    receipt = store.stage_next_batch(release_id, batch_size=1)
    checkpoint = store.checkpoint(release_id)

    assert receipt.staged_upserts == 1
    assert receipt.completed is True
    assert checkpoint["completed"] is True
    assert store.counts(release_id)["staged"] == 1
    assert receipt.automatic_promotion is False
    assert receipt.no_production_taxonomy_mutation is True
    assert receipt.no_knowledge_graph_mutation is True
