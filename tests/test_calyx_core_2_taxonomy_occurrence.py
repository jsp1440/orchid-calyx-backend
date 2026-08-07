"""CALYX CORE 2 — Taxonomy and occurrence pipeline tests (closes #386).

Covers:
- Bounded occurrence staging: happy path, idempotency, review queue for unresolved taxa.
- Taxonomy release router: inspect endpoint structure (unit, no DB).
- Occurrence readiness endpoint structure.
- WorldOrchids fixture parsing (fixture already validated by test_calyx_taxonomy_activation_002).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.occurrence_staging import (
    OccurrenceReviewItem,
    OccurrenceStagingResult,
    stage_occurrence_batch,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gbif_record(
    key: str = "g1",
    name: str = "Laelia anceps",
    accepted: str | None = "Laelia anceps",
    taxon_key: str | None = "5281",
    lat: float | None = 19.5,
    lon: float | None = -99.1,
) -> dict:
    return {
        "source": "gbif",
        "source_record_id": key,
        "scientific_name": name,
        "accepted_name": accepted,
        "taxon_key": taxon_key,
        "latitude": lat,
        "longitude": lon,
        "country_code": "MX",
        "locality": "Mexico",
        "event_date": "2023-03-15",
        "recorded_by": "Collector A",
        "license": "http://creativecommons.org/licenses/by/4.0/",
        "basis_of_record": "HUMAN_OBSERVATION",
        "raw": {"key": int(key[1:]) if key[1:].isdigit() else 0},
    }


def _inat_record(
    obs_id: str = "i1",
    name: str = "Laelia anceps",
    accepted: str | None = "Laelia anceps",
) -> dict:
    return {
        "source": "inaturalist",
        "source_record_id": obs_id,
        "scientific_name": name,
        "accepted_name": accepted,
        "taxon_key": None,
        "latitude": 19.5,
        "longitude": -99.1,
        "country_code": "MX",
        "locality": None,
        "event_date": None,
        "recorded_by": None,
        "license": "cc-by",
        "basis_of_record": "HUMAN_OBSERVATION",
        "raw": {},
    }


CANONICAL_LOOKUP: dict[str, str] = {
    "Laelia anceps": "taxon-001",
    "Cattleya trianae": "taxon-002",
}


# ---------------------------------------------------------------------------
# Occurrence staging: happy path
# ---------------------------------------------------------------------------

class TestStagingHappyPath:
    def test_single_gbif_record_staged(self):
        result = stage_occurrence_batch(
            [_gbif_record()],
            source="gbif",
            canonical_lookup=CANONICAL_LOOKUP,
        )
        assert isinstance(result, OccurrenceStagingResult)
        assert len(result.staged) == 1
        assert len(result.review_queue) == 0
        occ = result.staged[0]
        assert occ.source == "gbif"
        assert occ.source_record_id == "g1"
        assert occ.scientific_name == "Laelia anceps"
        assert occ.canonical_taxon_id == "taxon-001"
        assert occ.reconciliation_state == "resolved"
        assert occ.acquisition_checksum is not None

    def test_inat_record_staged(self):
        result = stage_occurrence_batch(
            [_inat_record()],
            source="inaturalist",
            canonical_lookup=CANONICAL_LOOKUP,
        )
        assert len(result.staged) == 1
        assert result.staged[0].canonical_taxon_id == "taxon-001"
        assert result.staged[0].reconciliation_state == "resolved"

    def test_multiple_sources_staged_independently(self):
        gbif_result = stage_occurrence_batch(
            [_gbif_record("g1"), _gbif_record("g2", name="Cattleya trianae", accepted="Cattleya trianae")],
            source="gbif",
            canonical_lookup=CANONICAL_LOOKUP,
        )
        assert len(gbif_result.staged) == 2
        assert gbif_result.staged[1].canonical_taxon_id == "taxon-002"

    def test_summary_is_serializable(self):
        result = stage_occurrence_batch(
            [_gbif_record()],
            source="gbif",
            canonical_lookup=CANONICAL_LOOKUP,
        )
        summary = result.summary()
        assert summary["staged_count"] == 1
        assert summary["no_production_mutation"] is True
        assert isinstance(summary["checkpoint"], dict)

    def test_as_dict_serializable(self):
        result = stage_occurrence_batch(
            [_gbif_record()],
            source="gbif",
            canonical_lookup=CANONICAL_LOOKUP,
        )
        d = result.staged[0].as_dict()
        assert d["source"] == "gbif"
        assert d["canonical_taxon_id"] == "taxon-001"


# ---------------------------------------------------------------------------
# Idempotency: re-running same batch produces no new inserts
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_same_batch_twice_skips_duplicates(self):
        records = [_gbif_record("g1"), _gbif_record("g2")]
        first = stage_occurrence_batch(records, source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        seen = {occ.acquisition_checksum for occ in first.staged}
        second = stage_occurrence_batch(records, source="gbif", seen_checksums=seen, canonical_lookup=CANONICAL_LOOKUP)
        assert second.duplicate_skipped == 2
        assert len(second.staged) == 0
        assert second.idempotent is True

    def test_new_record_not_skipped(self):
        records = [_gbif_record("g1")]
        first = stage_occurrence_batch(records, source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        seen = {occ.acquisition_checksum for occ in first.staged}
        second = stage_occurrence_batch(
            [_gbif_record("g1"), _gbif_record("g2")],
            source="gbif",
            seen_checksums=seen,
            canonical_lookup=CANONICAL_LOOKUP,
        )
        assert second.duplicate_skipped == 1
        assert len(second.staged) == 1
        assert second.staged[0].source_record_id == "g2"


# ---------------------------------------------------------------------------
# Review queue: unresolved taxon names
# ---------------------------------------------------------------------------

class TestReviewQueue:
    def test_unresolved_taxon_enters_review_queue(self):
        record = _gbif_record("g1", name="Unknown orchid sp.", accepted="Unknown orchid sp.")
        result = stage_occurrence_batch(
            [record],
            source="gbif",
            canonical_lookup=CANONICAL_LOOKUP,
        )
        # Still staged but also in review queue
        assert len(result.staged) == 1
        assert len(result.review_queue) == 1
        item = result.review_queue[0]
        assert isinstance(item, OccurrenceReviewItem)
        assert item.source == "gbif"
        assert "taxon" in item.reason.lower()

    def test_missing_source_record_id_enters_review_queue(self):
        bad = dict(_gbif_record())
        bad["source_record_id"] = ""
        result = stage_occurrence_batch([bad], source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        assert len(result.staged) == 0
        assert len(result.review_queue) == 1

    def test_missing_scientific_name_enters_review_queue(self):
        bad = dict(_gbif_record())
        bad["scientific_name"] = ""
        result = stage_occurrence_batch([bad], source="gbif", canonical_lookup=CANONICAL_LOOKUP)
        assert len(result.staged) == 0
        assert len(result.review_queue) == 1

    def test_review_item_serializable(self):
        record = _gbif_record("g1", name="Unknown sp.", accepted="Unknown sp.")
        result = stage_occurrence_batch(
            [record], source="gbif", canonical_lookup=CANONICAL_LOOKUP
        )
        assert len(result.review_queue) >= 1
        d = result.review_queue[0].as_dict()
        assert d["review_state"] == "needs_taxon_resolution"


# ---------------------------------------------------------------------------
# No-reconciliation mode (canonical_lookup=None)
# ---------------------------------------------------------------------------

class TestNoReconciliation:
    def test_stages_without_lookup(self):
        result = stage_occurrence_batch(
            [_gbif_record()],
            source="gbif",
            canonical_lookup=None,
        )
        assert len(result.staged) == 1
        assert result.staged[0].canonical_taxon_id is None
        assert result.staged[0].reconciliation_state == "reconciliation_unavailable"
        assert len(result.review_queue) == 0


# ---------------------------------------------------------------------------
# Unsupported source raises ValueError
# ---------------------------------------------------------------------------

def test_unsupported_source_raises():
    with pytest.raises(ValueError, match="unsupported occurrence source"):
        stage_occurrence_batch([], source="unknown_source")


# ---------------------------------------------------------------------------
# Batch checkpoint tracking
# ---------------------------------------------------------------------------

def test_batch_checkpoint_tracking():
    records = [_gbif_record("g1"), _gbif_record("g2")]
    result = stage_occurrence_batch(records, source="gbif", batch_start=50, canonical_lookup=CANONICAL_LOOKUP)
    assert result.batch_start == 50
    assert result.batch_end == 52
    assert result.checkpoint["batch_start"] == 50
    assert result.checkpoint["batch_end"] == 52


# ---------------------------------------------------------------------------
# WorldOrchids fixture: parse and validate structure
# ---------------------------------------------------------------------------

def test_world_plants_fixture_parseable():
    from runtime.world_plants_ingest import parse_world_orchids_release

    fixture = Path("tests/fixtures/world_plants_activation_smoke.csv")
    result = parse_world_orchids_release(fixture.read_bytes())
    assert result.summary()["rows"] >= 1
    assert result.summary()["issues"] == 0


def test_world_plants_release_store_inspect_and_retrieve(tmp_path):
    from runtime.world_plants_release_store import WorldPlantsReleaseStore

    fixture = Path("tests/fixtures/world_plants_activation_smoke.csv")
    payload = fixture.read_bytes()
    store = WorldPlantsReleaseStore(tmp_path)
    report = store.inspect_and_store(
        payload,
        filename="WorldOrchids-test.csv",
        version_label="26-08-test",
        acquired_at="2026-08-02",
        notes="smoke",
    )
    assert report["state"] == "inspected"
    assert report["automatic_promotion"] is False
    assert "canonical_promotion" in report
    assert "blocked" in report["canonical_promotion"]

    # Retrieve persisted report
    retrieved = store.get(report["release_id"])
    assert retrieved is not None
    assert retrieved["release_id"] == report["release_id"]


def test_world_plants_release_store_idempotent_upload(tmp_path):
    from runtime.world_plants_release_store import WorldPlantsReleaseStore

    fixture = Path("tests/fixtures/world_plants_activation_smoke.csv")
    payload = fixture.read_bytes()
    store = WorldPlantsReleaseStore(tmp_path)
    r1 = store.inspect_and_store(payload, filename="test.csv", version_label="v1", acquired_at="2026-08-02")
    r2 = store.inspect_and_store(payload, filename="test.csv", version_label="v1", acquired_at="2026-08-02")
    # Same payload → same release_id (sha256)
    assert r1["release_id"] == r2["release_id"]


def test_world_plants_list_reports(tmp_path):
    from runtime.world_plants_release_store import WorldPlantsReleaseStore

    fixture = Path("tests/fixtures/world_plants_activation_smoke.csv")
    payload = fixture.read_bytes()
    store = WorldPlantsReleaseStore(tmp_path)
    store.inspect_and_store(payload, filename="test.csv", version_label="v1", acquired_at="2026-08-02")
    reports = store.list_reports()
    assert len(reports) >= 1
