from app.executive_telemetry.harvesters import normalize_harvester
from app.executive_telemetry.source_metrics import enrich_source_row


def test_gbif_profile_preserves_live_metrics_and_calculates_completion() -> None:
    row = {
        "id": "gbif",
        "name": "GBIF",
        "source": "GBIF occurrence backbone",
        "enabled": True,
        "state": "running",
        "rows_processed": 1_000_000,
        "rows_inserted": 900_000,
        "heartbeat_at": "2026-07-27T05:00:00+00:00",
        "checkpoint": "audit_ecological_relationship_graph_gaps",
        "details": {
            "target_records": 5_000_000,
            "queue_remaining": 4_000_000,
            "records_per_minute": 10_000,
            "source_version": "2026-07",
        },
    }
    payload = normalize_harvester(row, include_operations=False)
    assert payload["records_processed"] == 1_000_000
    assert payload["records_inserted"] == 900_000
    assert payload["target_records"] == 5_000_000
    assert payload["completion_percentage"] == 20.0
    assert payload["duplicate_count"] == 100_000
    assert payload["duplicate_rate"] == 10.0
    assert payload["queue_remaining"] == 4_000_000
    assert payload["throughput"] == 10_000
    assert payload["estimated_completion"] == 400.0
    assert payload["version"] == "2026-07"
    assert payload["schedule"] == "daily"
    assert payload["allowed_actions"] == {}


def test_unavailable_source_remains_truthfully_unavailable() -> None:
    row = {
        "id": "globi",
        "name": "GloBI",
        "source": "Interaction records",
        "enabled": False,
        "state": "unknown",
        "errors": ["Database telemetry unavailable"],
        "checkpoint": "audit_missing_pollinator_data",
    }
    payload = normalize_harvester(row)
    assert payload["status"] == "unavailable"
    assert payload["records_processed"] == 0
    assert payload["target_records"] == 250_000
    assert payload["calyx_context"]["recommendation_signal"] == "unavailable"
    assert payload["failures"] == ["Database telemetry unavailable"]


def test_source_profile_extracts_source_specific_keys() -> None:
    row = {
        "id": "eol_traitbank",
        "rows_processed": 0,
        "rows_inserted": 0,
        "details": {
            "traits_processed": 125_000,
            "traits_inserted": 120_000,
            "duplicates": 5_000,
        },
    }
    enriched = enrich_source_row(row)
    assert enriched["rows_processed"] == 125_000
    assert enriched["rows_inserted"] == 120_000
    assert enriched["duplicates"] == 5_000
    assert enriched["target_records"] == 500_000
    assert enriched["schedule"] == "weekly"
