from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from runtime.world_plants_staging import PostgresWorldPlantsStagingStore

TEST_DATABASE_URL = os.getenv("WORLD_PLANTS_STAGING_TEST_DATABASE_URL")


def _release(rows: list[str]) -> bytes:
    header = "Taxon|Number|Name|Literature|TrivialName|Distribution|Synonyms|Status|Remarks|ConservationStatus|Photo|Orientation|Author"
    return (header + "\n" + "\n".join(rows) + "\n").encode("latin-1")


def _row(
    code: str,
    number: str,
    name: str,
    *,
    distribution: str = "",
    synonyms: str = "",
    status: str = "",
) -> str:
    fields = [
        code,
        number,
        name,
        "literature",
        "",
        distribution,
        synonyms,
        status,
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
    assert len(fields) == 22
    return "|".join(fields)


@pytest.fixture()
def store():
    if not TEST_DATABASE_URL:
        pytest.skip("WORLD_PLANTS_STAGING_TEST_DATABASE_URL is not configured")
    engine = create_engine(TEST_DATABASE_URL)
    migration = Path("migrations/107_world_plants_release_staging.sql").read_text(encoding="utf-8")
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS taxonomy_pipeline CASCADE"))
        connection.exec_driver_sql(migration)
    yield PostgresWorldPlantsStagingStore(engine)
    engine.dispose()


def test_bounded_staging_is_durable_resumable_and_idempotent(store):
    payload = _release(
        [
            _row("G", "135.1", "Cattleya Lindl."),
            _row("S", "", "Cattleya labiata Lindl.", distribution="Brazil"),
            _row("S", "", "Cattleya mossiae C. Parker ex Hook."),
        ]
    )
    release_id, parsed = store.register_release(
        payload,
        version_label="26-08",
        filename="WorldOrchids 26-08.csv",
        acquired_at="2026-08-02",
    )
    assert len(parsed.rows) == 3

    first = store.stage_next_batch(release_id, batch_size=2)
    assert first.batch_start == 0
    assert first.batch_end == 2
    assert first.completed is False
    assert first.total_staged == 2

    restarted = PostgresWorldPlantsStagingStore(store.engine)
    second = restarted.stage_next_batch(release_id, batch_size=2)
    assert second.batch_start == 2
    assert second.batch_end == 3
    assert second.completed is True
    assert second.total_staged == 3
    assert restarted.checkpoint(release_id)["completed"] is True

    replay = restarted.stage_next_batch(release_id, batch_size=2)
    assert replay.batch_start == 3
    assert replay.batch_end == 3
    assert replay.staged_upserts == 0
    assert replay.total_staged == 3


def test_duplicate_identity_enters_review_queue_without_activation(store):
    duplicate = _row("S", "", "Cattleya testensis Author")
    payload = _release([duplicate, duplicate])
    release_id, _ = store.register_release(
        payload,
        version_label="duplicate-test",
        filename="duplicate.csv",
        acquired_at="2026-08-02",
    )
    receipt = store.stage_next_batch(release_id, batch_size=100)
    report = store.change_report(release_id)

    assert receipt.completed is True
    assert report is not None
    assert report["summary"]["duplicate_identities"] == 1
    assert store.counts(release_id)["open_review"] == 1
    assert receipt.automatic_promotion is False
    assert receipt.no_production_taxonomy_mutation is True
    assert receipt.no_knowledge_graph_mutation is True


def test_change_report_separates_supported_change_categories(store):
    baseline = _release(
        [
            _row("G", "135.1", "Cattleya Lindl."),
            _row("S", "900", "Cattleya oldname Author", synonyms="= Old synonym"),
            _row("S", "", "Cattleya removed Author"),
        ]
    )
    baseline_id, _ = store.register_release(
        baseline,
        version_label="baseline",
        filename="baseline.csv",
        acquired_at="2026-07-01",
    )
    store.stage_next_batch(baseline_id, batch_size=100)

    current = _release(
        [
            _row("G", "135.1", "Cattleya Lindl."),
            _row("S", "900", "Cattleya newname Author", synonyms="= New synonym"),
            _row("S", "", "Cattleya added Author"),
        ]
    )
    current_id, _ = store.register_release(
        current,
        version_label="current",
        filename="current.csv",
        acquired_at="2026-08-02",
    )
    store.stage_next_batch(current_id, batch_size=100)
    report = store.generate_change_report(current_id, baseline_id)

    assert report["summary"]["added_taxa"] == 2
    assert report["summary"]["removed_taxa"] == 2
    assert report["summary"]["accepted_name_change_candidates"] == 1
    candidate = report["accepted_name_change_candidates"][0]
    assert candidate["world_plants_number"] == "900"
    assert candidate["review_required"] is True
    assert report["owner_approval_required_for_activation"] is True
    assert report["automatic_promotion"] is False


def test_source_payload_is_preserved_byte_for_byte(store):
    payload = _release([_row("S", "", "Cattleya labiata Lindl.", distribution="Brasil")])
    release_id, parsed = store.register_release(
        payload,
        version_label="byte-proof",
        filename="latin1.csv",
        acquired_at="2026-08-02",
    )
    assert parsed.source_encoding in {"utf-8", "latin-1"}
    assert store.source_payload(release_id) == payload
