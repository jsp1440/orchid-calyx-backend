"""Deterministic handler for the ``source_registry_refresh`` mission.

The Brain source registry (``oc_sources.sources``, migration 081) records each
registered literature/document source, its status and its last scan. This
handler takes an owner-approved, bounded snapshot of those rows in the
mission ``input_manifest`` and returns a refresh *plan* for human review:
which sources are stale, never scanned, failing, or inconsistent, and which a
reviewer may want to rescan.

It is deliberately narrow:

* no model/provider call and no network access, so no source is contacted
  and no scan is started;
* no database read or write of its own (the mission framework stores the
  returned plan as the mission output manifest in ``oc_missions``), so
  ``oc_sources`` is never mutated;
* no wall-clock read: ``as_of`` is part of the manifest, so the same manifest
  always produces the same plan;
* no approval: every recommendation is a proposal whose state is always
  ``awaiting_human_review``. ``REFRESH_RECOMMENDED`` never means a refresh ran.

Malformed or out-of-contract manifests fail closed with ``ValueError`` whose
message starts with ``SOURCE_REGISTRY_REFRESH_MANIFEST_INVALID`` so the
mission framework records a failed job instead of producing a partial plan.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

MAX_SOURCES = 200
MAX_LABEL_LENGTH = 500
MAX_SOURCE_ID_LENGTH = 200
MAX_SOURCE_TYPE_LENGTH = 64
MAX_TIMESTAMP_LENGTH = 64
MIN_MAX_AGE_DAYS = 1
MAX_MAX_AGE_DAYS = 3650
# oc_sources counters are BIGINT.
MAX_COUNT = 2**63 - 1

SOURCE_STATUSES = frozenset({"ACTIVE", "PAUSED", "ERROR"})
SCAN_STATUSES = frozenset({"RUNNING", "COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"})
COUNT_FIELDS = ("total_documents", "total_processed", "total_failed")
_SOURCE_TYPE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

ALLOWED_MANIFEST_KEYS = frozenset({"source", "as_of", "max_age_days", "sources"})
REQUIRED_SOURCE_KEYS = frozenset({"source_id", "source_name", "source_type", "status"})
ALLOWED_SOURCE_KEYS = REQUIRED_SOURCE_KEYS | {
    "last_scan",
    "last_scan_status",
    *COUNT_FIELDS,
}


def _invalid(detail: str) -> ValueError:
    return ValueError(f"SOURCE_REGISTRY_REFRESH_MANIFEST_INVALID:{detail}")


def _bounded_string(value: Any, name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{name}_not_string")
    stripped = value.strip()
    if not stripped:
        raise _invalid(f"{name}_required")
    if len(stripped) > limit:
        raise _invalid(f"{name}_too_long>{limit}")
    return stripped


def _timestamp(value: Any, name: str) -> datetime:
    text = _bounded_string(value, name, MAX_TIMESTAMP_LENGTH)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{name}_not_iso8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        # A naive timestamp has no defined instant; never guess a zone.
        raise _invalid(f"{name}_timezone_required")
    try:
        return parsed.astimezone(UTC)
    except OverflowError as exc:
        raise _invalid(f"{name}_out_of_range") from exc


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _count(value: Any, name: str) -> int:
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(f"{name}_not_int")
    if value < 0 or value > MAX_COUNT:
        raise _invalid(f"{name}_out_of_range")
    return value


def validate_source_registry_refresh_manifest(
    manifest: Any,
) -> tuple[str, datetime, int, list[dict[str, Any]]]:
    """Return ``(source, as_of, max_age_days, sources)`` or raise (fail closed)."""
    if not isinstance(manifest, Mapping):
        raise _invalid("manifest_not_object")
    unknown = sorted(str(key) for key in set(manifest) - ALLOWED_MANIFEST_KEYS)
    if unknown:
        raise _invalid(f"unknown_manifest_keys={','.join(unknown)}")
    label = _bounded_string(manifest.get("source"), "source", MAX_LABEL_LENGTH)
    as_of = _timestamp(manifest.get("as_of"), "as_of")
    max_age_days = manifest.get("max_age_days")
    if isinstance(max_age_days, bool) or not isinstance(max_age_days, int):
        raise _invalid("max_age_days_not_int")
    if not MIN_MAX_AGE_DAYS <= max_age_days <= MAX_MAX_AGE_DAYS:
        raise _invalid(
            f"max_age_days_out_of_range={MIN_MAX_AGE_DAYS}..{MAX_MAX_AGE_DAYS}"
        )
    rows = manifest.get("sources")
    if not isinstance(rows, list) or not rows:
        raise _invalid("sources_required")
    if len(rows) > MAX_SOURCES:
        raise _invalid(f"too_many_sources>{MAX_SOURCES}")

    cleaned: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_names: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise _invalid(f"source_{index}_not_object")
        keys = set(row)
        unknown_fields = sorted(str(key) for key in keys - ALLOWED_SOURCE_KEYS)
        if unknown_fields:
            raise _invalid(f"source_{index}_unknown_fields={','.join(unknown_fields)}")
        missing = sorted(REQUIRED_SOURCE_KEYS - keys)
        if missing:
            raise _invalid(f"source_{index}_missing_fields={','.join(missing)}")
        item = _validate_source(index, row)
        if item["source_id"] in seen_ids:
            raise _invalid(f"source_{index}_duplicate_source_id")
        seen_ids.add(item["source_id"])
        # oc_sources.sources is UNIQUE (source_name, source_type).
        name_key = (item["source_name"], item["source_type"])
        if name_key in seen_names:
            raise _invalid(f"source_{index}_duplicate_name_and_type")
        seen_names.add(name_key)
        cleaned.append(item)
    return label, as_of, max_age_days, cleaned


def _validate_source(index: int, row: Mapping[str, Any]) -> dict[str, Any]:
    prefix = f"source_{index}"
    item: dict[str, Any] = {
        "source_id": _bounded_string(
            row["source_id"], f"{prefix}_source_id", MAX_SOURCE_ID_LENGTH
        ),
        "source_name": _bounded_string(
            row["source_name"], f"{prefix}_source_name", MAX_LABEL_LENGTH
        ),
        "source_type": _bounded_string(
            row["source_type"], f"{prefix}_source_type", MAX_SOURCE_TYPE_LENGTH
        ),
    }
    if not _SOURCE_TYPE_PATTERN.match(item["source_type"]):
        raise _invalid(f"{prefix}_source_type_not_code")
    status = row["status"]
    if not isinstance(status, str) or status not in SOURCE_STATUSES:
        raise _invalid(f"{prefix}_status_not_allowed")
    item["status"] = status

    last_scan = row.get("last_scan")
    item["last_scan"] = (
        None if last_scan is None else _timestamp(last_scan, f"{prefix}_last_scan")
    )
    scan_status = row.get("last_scan_status")
    if scan_status is not None and (
        not isinstance(scan_status, str) or scan_status not in SCAN_STATUSES
    ):
        raise _invalid(f"{prefix}_last_scan_status_not_allowed")
    item["last_scan_status"] = scan_status
    for name in COUNT_FIELDS:
        value = row.get(name)
        item[name] = None if value is None else _count(value, f"{prefix}_{name}")
    return item


def _assess(
    item: dict[str, Any], as_of: datetime, max_age: timedelta
) -> dict[str, Any]:
    findings: list[str] = []
    last_scan: datetime | None = item["last_scan"]
    age_days: float | None = None
    scan_status = item["last_scan_status"]
    if last_scan is None and scan_status not in {None, "RUNNING"}:
        # finish_scan always stamps oc_sources.sources.last_scan, so a finished
        # scan without a timestamp is a self-contradictory snapshot. A RUNNING
        # first scan legitimately has none yet.
        freshness = "CONTRADICTORY"
        findings.append("LAST_SCAN_STATUS_WITHOUT_TIMESTAMP")
    elif last_scan is None:
        freshness = "NEVER_SCANNED"
    elif last_scan > as_of:
        # The snapshot contradicts itself; do not pick a side.
        freshness = "CONTRADICTORY"
        findings.append("LAST_SCAN_AFTER_AS_OF")
    else:
        age = as_of - last_scan
        age_days = round(age.total_seconds() / 86400, 6)
        freshness = "STALE" if age > max_age else "FRESH"

    if scan_status is None:
        findings.append("LAST_SCAN_STATUS_UNKNOWN")
    elif scan_status == "FAILED":
        findings.append("LAST_SCAN_FAILED")
    elif scan_status == "COMPLETED_WITH_ERRORS":
        findings.append("LAST_SCAN_COMPLETED_WITH_ERRORS")
    if item["status"] == "ERROR":
        findings.append("SOURCE_STATUS_ERROR")

    counts = {name: item[name] for name in COUNT_FIELDS}
    if any(value is None for value in counts.values()):
        findings.append("DOCUMENT_COUNTS_UNKNOWN")
    elif counts["total_processed"] + counts["total_failed"] > counts["total_documents"]:
        findings.append("DOCUMENT_COUNTS_INCONSISTENT")
    elif counts["total_failed"]:
        findings.append("DOCUMENTS_FAILED")

    if item["status"] == "PAUSED":
        # A pause is an operator decision; this plan never overrides it.
        recommendation = "NO_REFRESH_SOURCE_PAUSED"
    elif scan_status == "RUNNING":
        recommendation = "NO_REFRESH_SCAN_IN_PROGRESS"
    elif (
        item["status"] == "ERROR"
        or scan_status == "FAILED"
        or freshness == "CONTRADICTORY"
        or "DOCUMENT_COUNTS_INCONSISTENT" in findings
    ):
        recommendation = "OPERATOR_ATTENTION"
    elif freshness in {"NEVER_SCANNED", "STALE"}:
        recommendation = "REFRESH_RECOMMENDED"
    else:
        recommendation = "NO_REFRESH_NEEDED"

    return {
        "source_id": item["source_id"],
        "source_name": item["source_name"],
        "source_type": item["source_type"],
        "status": item["status"],
        "last_scan": None if last_scan is None else _iso(last_scan),
        "last_scan_status": scan_status,
        "age_days": age_days,
        "freshness": freshness,
        "findings": findings,
        "recommendation": recommendation,
        "refresh_executed": False,
        "human_review_required": True,
        **counts,
    }


def build_source_registry_refresh_plan(manifest: Any) -> dict[str, Any]:
    """Build a deterministic, human-review-only source registry refresh plan."""
    label, as_of, max_age_days, sources = validate_source_registry_refresh_manifest(
        manifest
    )
    max_age = timedelta(days=max_age_days)
    assessments = [
        _assess(item, as_of, max_age)
        for item in sorted(sources, key=lambda row: row["source_id"])
    ]
    freshness_counts: dict[str, int] = {}
    recommendation_counts: dict[str, int] = {}
    for item in assessments:
        freshness_counts[item["freshness"]] = (
            freshness_counts.get(item["freshness"], 0) + 1
        )
        recommendation_counts[item["recommendation"]] = (
            recommendation_counts.get(item["recommendation"], 0) + 1
        )
    summary = {
        "sources_assessed": len(assessments),
        "freshness": dict(sorted(freshness_counts.items())),
        "recommendations": dict(sorted(recommendation_counts.items())),
    }
    digest = hashlib.sha256(
        json.dumps(
            {
                "source": label,
                "as_of": _iso(as_of),
                "max_age_days": max_age_days,
                "assessments": assessments,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "status": "ok",
        "mission_type": "source_registry_refresh",
        "artifact_type": "source_registry_refresh_plan",
        "review_state": "awaiting_human_review",
        "human_review_required": True,
        "scientific_authority": "none",
        "scientific_conclusions_published": False,
        "approval_recorded": False,
        "refresh_executed": False,
        "scan_started": False,
        "source_registry_mutated": False,
        "provider_called": False,
        "external_network_called": False,
        "domain_database_written": False,
        "canonical_graph_mutated": False,
        "taxonomy_mutated": False,
        "snapshot_source": label,
        "as_of": _iso(as_of),
        "max_age_days": max_age_days,
        "summary": summary,
        "assessments": assessments,
        "plan_digest": digest,
    }
