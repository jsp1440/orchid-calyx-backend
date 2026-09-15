"""Scout persistence acceptance against the existing isolated ledger CI service."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
import pytest

from app.intake import intelligence_repository
from app.intake.intelligence_repository import get_intelligence_item
from app.intake.repository import get_source
from app.intake.technology_scout import (
    SCOUT_VERSION,
    TRIAGE_DIMENSIONS,
    ScoutBatch,
    ScoutMetadata,
    ingest_scout_batch,
)

DATABASE_URL = os.getenv("INTELLIGENCE_LEDGER_DATABASE_URL")
CI_DATABASE_URL = (
    "postgresql://postgres:postgres@localhost:5432/orchid_intelligence_test"
)
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="INTELLIGENCE_LEDGER_DATABASE_URL not set"
)


@pytest.fixture(autouse=True)
def local_ledger(monkeypatch):
    if DATABASE_URL != CI_DATABASE_URL:
        pytest.fail(
            "Scout persistence tests require the fixed isolated ledger CI database"
        )
    monkeypatch.setenv("DATABASE_URL", DATABASE_URL)
    with psycopg.connect(DATABASE_URL) as connection:
        for name in (
            "070_knowledge_intake.sql",
            "108_intelligence_assimilation_ledger.sql",
        ):
            connection.execute((Path("migrations") / name).read_text(encoding="utf-8"))


def metadata(key, **changes):
    return ScoutMetadata.model_validate(
        {
            "title": "Hybrid search fixture",
            "doi": f"10.5555/oc-scout-fixture-{key}",
            "primary_url": f"https://example.invalid/scout/{key}",
            "source_kind": "user",
            **changes,
        }
    )


def ingest(*items):
    return ingest_scout_batch(ScoutBatch(items=list(items)))["items"]


def test_replay_keeps_one_source_observation_and_no_scientific_or_task_rows():
    lead = metadata("replay")
    first = ingest(lead)[0]
    replay = ingest(lead)[0]
    assert replay["id"] == first["id"]
    assert replay["new_observation"] is False
    assert replay["observation_count"] == 1
    restored = get_intelligence_item(first["id"])
    assert len(restored["observations"]) == len(restored["events"]) == 1
    source = get_source(restored["observations"][0]["source_id"])
    assert source["entities"] == source["relationships"] == source["tasks"] == []
    assert restored["canonical_promotion_prohibited"] is True
    assert restored["external_contact_prohibited"] is True


def test_changed_source_keeps_both_versioned_assessments_and_doi_identity():
    first = ingest(metadata("changed"))[0]
    second = ingest(
        metadata(
            "changed", title="Multispectral imaging fixture", source_kind="oc_harvester"
        )
    )[0]
    assert first["id"] == second["id"]
    assert second["observation_count"] == 2
    restored = get_intelligence_item(first["id"])
    assessments = [
        obs["raw_snapshot"]["technology_scout"] for obs in restored["observations"]
    ]
    assert {assessment["source"]["title"] for assessment in assessments} == {
        "Hybrid search fixture",
        "Multispectral imaging fixture",
    }
    for assessment in assessments:
        assert assessment["schema"] == SCOUT_VERSION
        assert set(assessment["triage"]) == set(TRIAGE_DIMENSIONS)
        assert all(
            dimension["score"] is None for dimension in assessment["triage"].values()
        )
        assert assessment["assessment_basis"] == "METADATA_ONLY"
        assert assessment["engineering_dispatch_authorized"] is False


@pytest.mark.parametrize("lifecycle", ["REJECTED", "VERIFIED", "COMPARED", "ACTIONED"])
def test_rediscovery_cannot_reset_reviewed_lifecycle(lifecycle):
    first = ingest(metadata(lifecycle))[0]
    with psycopg.connect(DATABASE_URL) as connection:
        connection.execute(
            "UPDATE oc_intake.intelligence_items SET lifecycle=%s, "
            "verification_required=FALSE, knowledge_delta='REQUIRES_REVIEW' WHERE id=%s",
            (lifecycle, first["id"]),
        )
    replay = ingest(metadata(lifecycle, title="Changed hybrid search metadata"))[0]
    assert replay["lifecycle"] == lifecycle
    restored = get_intelligence_item(first["id"])
    assert restored["verification_required"] is False
    assert restored["knowledge_delta"] == "REQUIRES_REVIEW"
    assert restored["canonical_promotion_prohibited"] is True


def test_partial_batch_retry_recovers_without_duplicate_observations(monkeypatch):
    original = intelligence_repository.record_intelligence_items
    calls = 0

    def interrupt(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected failure after source persistence")
        return original(**kwargs)

    monkeypatch.setattr(intelligence_repository, "record_intelligence_items", interrupt)
    batch = [metadata("retry-first"), metadata("retry-second")]
    with pytest.raises(RuntimeError, match="injected failure"):
        ingest(*batch)
    monkeypatch.setattr(intelligence_repository, "record_intelligence_items", original)
    receipts = ingest(*batch)
    assert [receipt["new_observation"] for receipt in receipts] == [False, True]
    assert all(receipt["observation_count"] == 1 for receipt in receipts)
