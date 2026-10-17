"""Deterministic tests for the source_registry_refresh mission handler (#1730)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from app.missions.registry import MISSION_TYPES
from app.missions.repositories import InMemoryMissionRepository
from app.missions.services import MissionService
from app.missions.source_registry_refresh import (
    MAX_LABEL_LENGTH,
    MAX_MAX_AGE_DAYS,
    MAX_SOURCE_ID_LENGTH,
    MAX_SOURCE_TYPE_LENGTH,
    MAX_SOURCES,
    build_source_registry_refresh_plan,
)

AS_OF = "2026-10-01T00:00:00Z"
CODE = "SOURCE_REGISTRY_REFRESH_MANIFEST_INVALID"


def row(source_id: Any, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source_id": source_id,
        "source_name": f"name-{source_id}",
        "source_type": "GOOGLE_DRIVE",
        "status": "ACTIVE",
        "last_scan": "2026-09-28T00:00:00Z",
        "last_scan_status": "COMPLETED",
        "total_documents": 10,
        "total_processed": 8,
        "total_failed": 0,
    }
    data.update(overrides)
    return data


def manifest(*rows: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "source": "fixture-snapshot-1",
        "as_of": AS_OF,
        "max_age_days": 7,
        "sources": list(rows),
    }
    data.update(overrides)
    return data


def by_id(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["source_id"]: item for item in plan["assessments"]}


def run_mission(input_manifest: dict[str, Any], key: str) -> tuple[MissionService, int]:
    service = MissionService(InMemoryMissionRepository())
    mission = service.create(
        {
            "mission_key": key,
            "title": "Source registry refresh",
            "description": "Plan source registry refreshes for human review.",
            "mission_type": "source_registry_refresh",
            "requested_by": "owner",
            "priority": 50,
            "maximum_runs": 1,
            "input_manifest": input_manifest,
            "allowed_actions": ["report_for_review"],
            "prohibited_actions": [
                "taxonomy_write",
                "canonical_graph_publish",
                "external_api_call",
            ],
            "idempotency_key": key,
        },
        {"auth_type": "owner_session"},
    )
    mission_id = mission["mission_id"]
    service.submit(mission_id, "owner", "ready")
    service.approve(mission_id, "owner", "approve", "approval-1730")
    service.queue(mission_id, "owner", "queue")
    service.execute_cycle("worker-source-refresh")
    return service, mission_id


def test_registry_contract_preserves_limits():
    mission_type = MISSION_TYPES["source_registry_refresh"]
    assert mission_type.handler == "source_registry_refresh"
    assert mission_type.risk_level == "medium"
    assert mission_type.write_scope == "read_only"
    assert mission_type.allowed_database_schemas == ()
    assert "oc_taxonomy" in mission_type.forbidden_database_schemas
    assert mission_type.human_approval_required is True
    assert mission_type.publication_authority_required is False
    assert mission_type.canonical_graph_writes_permitted is False
    assert mission_type.taxonomy_writes_prohibited is True


def test_plan_is_human_review_only_and_asserts_no_authority():
    plan = build_source_registry_refresh_plan(
        manifest(row("a"), row("b", last_scan=None))
    )

    assert plan["artifact_type"] == "source_registry_refresh_plan"
    assert plan["review_state"] == "awaiting_human_review"
    assert plan["human_review_required"] is True
    assert plan["scientific_authority"] == "none"
    for flag in (
        "scientific_conclusions_published",
        "approval_recorded",
        "refresh_executed",
        "scan_started",
        "source_registry_mutated",
        "provider_called",
        "external_network_called",
        "domain_database_written",
        "canonical_graph_mutated",
        "taxonomy_mutated",
    ):
        assert plan[flag] is False, flag
    for item in plan["assessments"]:
        assert item["refresh_executed"] is False
        assert item["human_review_required"] is True


def test_freshness_and_recommendations_are_classified():
    plan = build_source_registry_refresh_plan(
        manifest(
            row("fresh"),
            row("stale", last_scan="2026-09-01T00:00:00Z"),
            row("never", last_scan=None, last_scan_status=None),
            row("boundary", last_scan="2026-09-24T00:00:00Z"),
            row("future", last_scan="2026-10-02T00:00:00Z"),
            row("paused", status="PAUSED", last_scan="2025-01-01T00:00:00Z"),
            row("errored", status="ERROR"),
            row("failed", last_scan_status="FAILED"),
            row(
                "running", last_scan_status="RUNNING", last_scan="2026-01-01T00:00:00Z"
            ),
        )
    )
    items = by_id(plan)
    assert items["fresh"]["freshness"] == "FRESH"
    assert items["fresh"]["recommendation"] == "NO_REFRESH_NEEDED"
    assert items["fresh"]["age_days"] == 3.0
    assert items["stale"]["freshness"] == "STALE"
    assert items["stale"]["recommendation"] == "REFRESH_RECOMMENDED"
    assert items["never"]["freshness"] == "NEVER_SCANNED"
    assert items["never"]["age_days"] is None
    assert items["never"]["recommendation"] == "REFRESH_RECOMMENDED"
    assert "LAST_SCAN_STATUS_UNKNOWN" in items["never"]["findings"]
    # Exactly max_age_days old is not past the threshold.
    assert items["boundary"]["freshness"] == "FRESH"
    assert items["future"]["freshness"] == "CONTRADICTORY"
    assert "LAST_SCAN_AFTER_AS_OF" in items["future"]["findings"]
    assert items["future"]["recommendation"] == "OPERATOR_ATTENTION"
    # A pause is an operator decision; a stale paused source is not re-queued.
    assert items["paused"]["freshness"] == "STALE"
    assert items["paused"]["recommendation"] == "NO_REFRESH_SOURCE_PAUSED"
    assert items["errored"]["recommendation"] == "OPERATOR_ATTENTION"
    assert "SOURCE_STATUS_ERROR" in items["errored"]["findings"]
    assert items["failed"]["recommendation"] == "OPERATOR_ATTENTION"
    assert "LAST_SCAN_FAILED" in items["failed"]["findings"]
    assert items["running"]["recommendation"] == "NO_REFRESH_SCAN_IN_PROGRESS"
    assert plan["summary"]["sources_assessed"] == 9
    assert sum(plan["summary"]["recommendations"].values()) == 9


def test_document_counts_are_checked_not_assumed():
    plan = build_source_registry_refresh_plan(
        manifest(
            row("unknown", total_documents=None),
            row("inconsistent", total_documents=3, total_processed=3, total_failed=1),
            row("some-failed", total_failed=2),
        )
    )
    items = by_id(plan)
    assert "DOCUMENT_COUNTS_UNKNOWN" in items["unknown"]["findings"]
    assert items["unknown"]["total_documents"] is None
    assert items["unknown"]["recommendation"] == "NO_REFRESH_NEEDED"
    assert "DOCUMENT_COUNTS_INCONSISTENT" in items["inconsistent"]["findings"]
    assert items["inconsistent"]["recommendation"] == "OPERATOR_ATTENTION"
    assert "DOCUMENTS_FAILED" in items["some-failed"]["findings"]


def test_timezone_offsets_are_normalized_to_utc():
    plan = build_source_registry_refresh_plan(
        manifest(
            row("a", last_scan="2026-09-30T20:00:00-04:00"),
            as_of="2026-10-01T02:00:00+02:00",
        )
    )
    item = by_id(plan)["a"]
    assert plan["as_of"] == "2026-10-01T00:00:00Z"
    assert item["last_scan"] == "2026-10-01T00:00:00Z"
    assert item["age_days"] == 0.0


def test_plan_is_deterministic_order_independent_and_does_not_mutate_input():
    rows = [row("b"), row("a", last_scan=None), row("c", status="PAUSED")]
    original = manifest(*rows)
    snapshot = copy.deepcopy(original)
    first = build_source_registry_refresh_plan(original)
    second = build_source_registry_refresh_plan(
        manifest(*reversed(copy.deepcopy(rows)))
    )
    assert original == snapshot
    assert first == second
    assert [item["source_id"] for item in first["assessments"]] == ["a", "b", "c"]
    changed = build_source_registry_refresh_plan(manifest(*rows, max_age_days=1))
    assert changed["plan_digest"] != first["plan_digest"]


@pytest.mark.parametrize(
    ("bad_manifest", "detail"),
    [
        (None, "manifest_not_object"),
        ([], "manifest_not_object"),
        (manifest(row("a"), extra=1), "unknown_manifest_keys=extra"),
        (manifest(row("a"), source=""), "source_required"),
        (manifest(row("a"), source=5), "source_not_string"),
        (manifest(row("a"), as_of=None), "as_of_not_string"),
        (manifest(row("a"), as_of="yesterday"), "as_of_not_iso8601"),
        (manifest(row("a"), as_of="2026-10-01T00:00:00"), "as_of_timezone_required"),
        (manifest(row("a"), as_of="0001-01-01T00:00:00+05:00"), "as_of_out_of_range"),
        (manifest(row("a"), max_age_days=True), "max_age_days_not_int"),
        (manifest(row("a"), max_age_days=7.0), "max_age_days_not_int"),
        (manifest(row("a"), max_age_days="7"), "max_age_days_not_int"),
        (manifest(row("a"), max_age_days=0), "max_age_days_out_of_range"),
        (
            manifest(row("a"), max_age_days=MAX_MAX_AGE_DAYS + 1),
            "max_age_days_out_of_range",
        ),
        (manifest(), "sources_required"),
        (manifest(row("a"), sources="a"), "sources_required"),
        (manifest("a"), "source_0_not_object"),
        (manifest(row("a", configuration={})), "source_0_unknown_fields=configuration"),
        (manifest({"source_id": "a"}), "source_0_missing_fields="),
        (manifest(row(1)), "source_0_source_id_not_string"),
        (manifest(row(" ")), "source_0_source_id_required"),
        (manifest(row("a", source_type="drive")), "source_0_source_type_not_code"),
        (manifest(row("a", status="APPROVED")), "source_0_status_not_allowed"),
        (manifest(row("a", status=None)), "source_0_status_not_allowed"),
        (manifest(row("a", last_scan=0)), "source_0_last_scan_not_string"),
        (
            manifest(row("a", last_scan_status="DONE")),
            "source_0_last_scan_status_not_allowed",
        ),
        (manifest(row("a", total_documents=True)), "source_0_total_documents_not_int"),
        (manifest(row("a", total_failed=-1)), "source_0_total_failed_out_of_range"),
        (
            manifest(row("a", total_processed=2**63)),
            "source_0_total_processed_out_of_range",
        ),
        (
            manifest(row("a"), row("a", source_name="other")),
            "source_1_duplicate_source_id",
        ),
        (
            manifest(row("a"), row(" a ", source_name="other")),
            "source_1_duplicate_source_id",
        ),
        (
            manifest(row("a"), row("b", source_name="name-a")),
            "source_1_duplicate_name_and_type",
        ),
    ],
)
def test_out_of_contract_manifest_fails_closed(bad_manifest: Any, detail: str):
    with pytest.raises(ValueError, match=f"^{CODE}:{detail}"):
        build_source_registry_refresh_plan(bad_manifest)


def test_input_bounds_accept_values_at_the_limit():
    rows = [row(f"s{index}") for index in range(MAX_SOURCES - 1)]
    rows.append(
        row(
            "x" * MAX_SOURCE_ID_LENGTH,
            source_name="n" * MAX_LABEL_LENGTH,
            source_type="T" * MAX_SOURCE_TYPE_LENGTH,
            total_documents=2**63 - 1,
        )
    )
    plan = build_source_registry_refresh_plan(
        manifest(*rows, source="s" * MAX_LABEL_LENGTH, max_age_days=MAX_MAX_AGE_DAYS)
    )
    assert plan["summary"]["sources_assessed"] == MAX_SOURCES


@pytest.mark.parametrize(
    ("bad_manifest", "detail"),
    [
        (manifest(row("a"), source="s" * (MAX_LABEL_LENGTH + 1)), "source_too_long"),
        (manifest(*[row(f"s{i}") for i in range(MAX_SOURCES + 1)]), "too_many_sources"),
        (
            manifest(row("x" * (MAX_SOURCE_ID_LENGTH + 1))),
            "source_0_source_id_too_long",
        ),
        (
            manifest(row("a", source_name="n" * (MAX_LABEL_LENGTH + 1))),
            "source_0_source_name_too_long",
        ),
        (
            manifest(row("a", source_type="T" * (MAX_SOURCE_TYPE_LENGTH + 1))),
            "source_0_source_type_too_long",
        ),
        (
            manifest(row("a", last_scan="2026-09-28T00:00:00Z" + " " * 60 + "x")),
            "source_0_last_scan_too_long",
        ),
    ],
)
def test_input_bounds_fail_closed_past_the_limit(bad_manifest: Any, detail: str):
    with pytest.raises(ValueError, match=f"^{CODE}:{detail}"):
        build_source_registry_refresh_plan(bad_manifest)


def test_mission_lifecycle_completes_with_review_plan():
    service, mission_id = run_mission(
        manifest(row("a"), row("b", last_scan=None)), key="refresh-1"
    )

    completed = service.get(mission_id)
    assert completed["state"] == "completed"
    output = completed["output_manifest"]
    assert output["artifact_type"] == "source_registry_refresh_plan"
    assert output["review_state"] == "awaiting_human_review"
    assert output["refresh_executed"] is False
    assert output["taxonomy_mutated"] is False
    assert service.jobs(mission_id)[0]["state"] == "succeeded"


def test_mission_with_invalid_manifest_fails_and_does_not_complete():
    service, mission_id = run_mission(manifest(), key="refresh-bad")

    mission = service.get(mission_id)
    assert mission["state"] != "completed"
    assert mission["output_manifest"] == {}
    assert CODE in mission["last_error"]


def test_handler_module_has_no_provider_network_or_db_imports():
    source = Path("app/missions/source_registry_refresh.py").read_text(encoding="utf-8")
    for token in (
        "anthropic",
        "openai",
        "requests",
        "httpx",
        "urllib",
        "psycopg",
        "subprocess",
        "socket",
        "app.source_registry",
        "datetime.now",
        "utcnow",
        "time.time",
    ):
        assert token not in source, token


def test_finished_scan_status_without_timestamp_is_contradictory():
    plan = build_source_registry_refresh_plan(
        manifest(
            row("completed", last_scan=None, last_scan_status="COMPLETED"),
            row("failed", last_scan=None, last_scan_status="FAILED"),
            row("partial", last_scan=None, last_scan_status="COMPLETED_WITH_ERRORS"),
            row("first-running", last_scan=None, last_scan_status="RUNNING"),
        )
    )
    items = by_id(plan)
    for key in ("completed", "failed", "partial"):
        assert items[key]["freshness"] == "CONTRADICTORY", key
        assert "LAST_SCAN_STATUS_WITHOUT_TIMESTAMP" in items[key]["findings"], key
        assert items[key]["recommendation"] == "OPERATOR_ATTENTION", key
    # A first scan still running has no timestamp yet; that is not a conflict.
    assert items["first-running"]["freshness"] == "NEVER_SCANNED"
    assert items["first-running"]["findings"] == []
    assert items["first-running"]["recommendation"] == "NO_REFRESH_SCAN_IN_PROGRESS"
