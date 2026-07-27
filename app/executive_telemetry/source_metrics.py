from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


SOURCE_METRIC_PROFILES: dict[str, dict[str, Any]] = {
    "inaturalist": {
        "target_records": 1_000_000,
        "schedule": "daily",
        "metric_keys": ["observations", "records_processed", "rows_processed"],
        "inserted_keys": ["observations_inserted", "records_inserted", "rows_inserted"],
        "duplicate_keys": ["duplicates", "duplicate_count"],
        "queue_keys": ["queue_remaining", "remaining"],
        "throughput_keys": ["throughput", "records_per_minute"],
    },
    "gbif": {
        "target_records": 5_000_000,
        "schedule": "daily",
        "metric_keys": ["occurrences_processed", "records_processed", "rows_processed"],
        "inserted_keys": ["occurrences_inserted", "records_inserted", "rows_inserted"],
        "duplicate_keys": ["duplicates", "duplicate_count"],
        "queue_keys": ["queue_remaining", "remaining"],
        "throughput_keys": ["throughput", "records_per_minute"],
    },
    "world_plants_hassler": {
        "target_records": 50_000,
        "schedule": "weekly",
        "metric_keys": ["taxa_processed", "records_processed", "rows_processed"],
        "inserted_keys": ["taxa_inserted", "records_inserted", "rows_inserted"],
        "duplicate_keys": ["synonyms_collapsed", "duplicates", "duplicate_count"],
        "queue_keys": ["queue_remaining", "remaining"],
        "throughput_keys": ["throughput", "records_per_minute"],
    },
    "eol_traitbank": {
        "target_records": 500_000,
        "schedule": "weekly",
        "metric_keys": ["traits_processed", "records_processed", "rows_processed"],
        "inserted_keys": ["traits_inserted", "records_inserted", "rows_inserted"],
        "duplicate_keys": ["duplicates", "duplicate_count"],
        "queue_keys": ["queue_remaining", "remaining"],
        "throughput_keys": ["throughput", "records_per_minute"],
    },
    "globi": {
        "target_records": 250_000,
        "schedule": "weekly",
        "metric_keys": ["interactions_processed", "records_processed", "rows_processed"],
        "inserted_keys": ["interactions_inserted", "records_inserted", "rows_inserted"],
        "duplicate_keys": ["duplicates", "duplicate_count"],
        "queue_keys": ["queue_remaining", "remaining"],
        "throughput_keys": ["throughput", "records_per_minute"],
    },
    "pollinator_datasets": {
        "target_records": 100_000,
        "schedule": "weekly",
        "metric_keys": ["pollination_records_processed", "records_processed", "rows_processed"],
        "inserted_keys": ["pollination_records_inserted", "records_inserted", "rows_inserted"],
        "duplicate_keys": ["duplicates", "duplicate_count"],
        "queue_keys": ["queue_remaining", "remaining"],
        "throughput_keys": ["throughput", "records_per_minute"],
    },
}


def _first_number(data: dict[str, Any], keys: list[str], fallback: int | float | None = None):
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)):
            return value
    return fallback


def _freshness_label(timestamp: str | None) -> str:
    if not timestamp:
        return "unavailable"
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return timestamp
    age = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    seconds = max(int(age.total_seconds()), 0)
    if seconds < 60:
        return "less than 1 minute ago"
    if seconds < 3600:
        return f"{seconds // 60} minute(s) ago"
    if seconds < 86400:
        return f"{seconds // 3600} hour(s) ago"
    return f"{seconds // 86400} day(s) ago"


def enrich_source_row(row: dict[str, Any]) -> dict[str, Any]:
    source_id = str(row.get("id") or "")
    profile = SOURCE_METRIC_PROFILES.get(source_id, {})
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    combined = {**row, **details}

    processed = int(_first_number(combined, profile.get("metric_keys", []), row.get("rows_processed") or 0) or 0)
    inserted = int(_first_number(combined, profile.get("inserted_keys", []), row.get("rows_inserted") or 0) or 0)
    target = int(_first_number(combined, ["target_records"], profile.get("target_records")) or 0) or None
    duplicates = int(_first_number(combined, profile.get("duplicate_keys", []), max(processed - inserted, 0)) or 0)
    queue_remaining = _first_number(combined, profile.get("queue_keys", []))
    throughput = _first_number(combined, profile.get("throughput_keys", []))
    heartbeat = row.get("heartbeat_at") or row.get("last_run")

    estimated_completion = None
    if isinstance(queue_remaining, (int, float)) and isinstance(throughput, (int, float)) and throughput > 0:
        estimated_completion = round(float(queue_remaining) / float(throughput), 2)

    return {
        **row,
        "rows_processed": processed,
        "rows_inserted": inserted,
        "target_records": target,
        "duplicates": duplicates,
        "queue_remaining": queue_remaining,
        "throughput": throughput,
        "schedule": combined.get("schedule") or profile.get("schedule") or "unavailable",
        "estimated_completion": combined.get("estimated_completion") or estimated_completion,
        "freshness_label": _freshness_label(str(heartbeat) if heartbeat else None),
        "version": combined.get("source_version") or combined.get("version") or "unavailable",
    }
