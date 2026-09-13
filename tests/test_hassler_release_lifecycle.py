"""OC-COMPLETE-002 — exact Hassler release lifecycle classification tests.

These tests pin the three invariants the completion lane depends on:
unavailable is never zero, activation is never implied by upload or staging,
and the exact release identity is verified rather than assumed.
"""

from __future__ import annotations

import pytest

from runtime.hassler_release_lifecycle import (
    EXPECTED_ACQUIRED_AT,
    EXPECTED_FILENAME,
    EXPECTED_SHA256,
    EXPECTED_SIZE_BYTES,
    EXPECTED_VERSION_LABEL,
    Evidence,
    build_owner_exception_receipt,
    build_release_status_block,
    classify_release_lifecycle,
    enumerate_downstream_relink_impact,
    verify_source_identity,
)

EXACT_SNAPSHOT = {
    "filename": EXPECTED_FILENAME,
    "sha256": EXPECTED_SHA256,
    "size_bytes": EXPECTED_SIZE_BYTES,
    "version_label": EXPECTED_VERSION_LABEL,
    "acquired_at": EXPECTED_ACQUIRED_AT,
    "row_count": 1000,
}


def _exact_entry(state: str = "inspected", **snapshot_overrides):
    snapshot = dict(EXACT_SNAPSHOT)
    snapshot.update(snapshot_overrides)
    return {
        "release_id": EXPECTED_SHA256,
        "snapshot": snapshot,
        "state": state,
        "automatic_promotion": False,
    }


def _releases(*entries):
    return Evidence.of({"releases": list(entries)}, "test release list")


def _readiness(smoke_passed: bool):
    return Evidence.of(
        {
            "gates": [
                {"name": "owner_authentication", "status": "passed"},
                {
                    "name": "smoke_fixture",
                    "status": "passed" if smoke_passed else "blocked",
                    "evidence": "test gate",
                    "blocking_reason": None if smoke_passed else "smoke not run",
                },
            ]
        },
        "test readiness",
    )


def _staging(staged: int, completed: bool, next_row_index: int, change_report=None):
    return Evidence.of(
        {
            "checkpoint": {
                "next_row_index": next_row_index,
                "staged_count": staged,
                "completed": completed,
                "updated_at": "2026-08-22T00:00:00+00:00",
            },
            "counts": {"staged": staged, "open_review": 0},
            "change_report": change_report,
        },
        "test staging",
    )


# --- unavailable is never zero -------------------------------------------------


def test_unreadable_release_list_is_unavailable_not_absent():
    lifecycle = classify_release_lifecycle(
        releases=Evidence.unavailable("release list HTTP 503")
    )
    assert lifecycle["lifecycle_state"] == "UNAVAILABLE"
    assert lifecycle["durably_uploaded"] is None
    assert lifecycle["evidence_complete"] is False
    assert {item["probe"] for item in lifecycle["unavailable_evidence"]} == {
        "release_list",
        "release_detail",
        "readiness",
        "staging",
        "canonical_activation",
    }


def test_successful_empty_release_list_is_absent_not_unavailable():
    lifecycle = classify_release_lifecycle(releases=_releases())
    assert lifecycle["lifecycle_state"] == "ABSENT"
    assert lifecycle["durably_uploaded"] is False


def test_unavailable_staging_does_not_report_zero_staged_rows():
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry()),
        staging=Evidence.unavailable("durable staging query failed"),
    )
    assert lifecycle["staging"]["evidence"] == "unavailable"
    assert lifecycle["staging"]["staged_rows"] is None
    assert lifecycle["staging"]["complete"] is None
    assert lifecycle["lifecycle_state"] == "UPLOADED_INSPECTED"


def test_unavailable_smoke_gate_is_not_a_failed_gate():
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry()),
        readiness=Evidence.unavailable("readiness HTTP 500"),
    )
    assert lifecycle["smoke"]["verified"] is None
    assert lifecycle["smoke"]["evidence"] == "unavailable"


# --- lifecycle progression -----------------------------------------------------


def test_present_release_without_smoke_is_uploaded_inspected():
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry()), readiness=_readiness(False)
    )
    assert lifecycle["lifecycle_state"] == "UPLOADED_INSPECTED"
    assert lifecycle["durably_uploaded"] is True
    assert lifecycle["durable_release_state"] == "inspected"


def test_present_release_with_passed_smoke_is_smoke_verified():
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry()),
        readiness=_readiness(True),
        staging=_staging(0, False, 0),
    )
    assert lifecycle["lifecycle_state"] == "SMOKE_VERIFIED"


def test_partial_staging_is_staging_in_progress_and_resumable():
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry(state="staging")),
        readiness=_readiness(True),
        staging=_staging(400, False, 400),
    )
    assert lifecycle["lifecycle_state"] == "STAGING_IN_PROGRESS"
    assert lifecycle["staging"]["next_row_index"] == 400
    assert lifecycle["staging"]["expected_rows"] == 1000
    assert lifecycle["active_vs_staged"]["staged_release_id"] == EXPECTED_SHA256


def test_completed_staging_matching_row_count_is_staged_complete():
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry(state="staged")),
        readiness=_readiness(True),
        staging=_staging(1000, True, 1000, change_report={"summary": {}}),
    )
    assert lifecycle["lifecycle_state"] == "STAGED_COMPLETE"
    assert lifecycle["staging"]["change_report_present"] is True


def test_completed_checkpoint_with_short_row_count_is_not_staged_complete():
    """A completed flag alone must not overstate staging coverage."""
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry(state="staging")),
        readiness=_readiness(True),
        staging=_staging(900, True, 900),
    )
    assert lifecycle["lifecycle_state"] == "STAGING_IN_PROGRESS"


def test_newer_durable_release_supersedes_the_exact_release():
    newer = {
        "release_id": "f" * 64,
        "snapshot": {
            "filename": "WorldOrchids 26-09 (Sep 1 2026).csv",
            "sha256": "f" * 64,
            "version_label": "26-09",
            "acquired_at": "2026-09-01",
        },
        "state": "inspected",
    }
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry(state="staged"), newer),
        readiness=_readiness(True),
        staging=_staging(1000, True, 1000),
    )
    assert lifecycle["lifecycle_state"] == "SUPERSEDED"
    assert lifecycle["superseded_by"][0]["release_id"] == "f" * 64


def test_older_release_does_not_supersede():
    older = {
        "release_id": "a" * 64,
        "snapshot": {"sha256": "a" * 64, "acquired_at": "2026-01-01"},
        "state": "inspected",
    }
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry(), older), readiness=_readiness(False)
    )
    assert lifecycle["superseded"] is False
    assert lifecycle["lifecycle_state"] == "UPLOADED_INSPECTED"


# --- activation is separately protected ---------------------------------------


@pytest.mark.parametrize(
    "staging_evidence",
    [
        _staging(1000, True, 1000),
        _staging(500, False, 500),
    ],
)
def test_upload_and_staging_never_imply_activation(staging_evidence):
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry(state="staged")),
        readiness=_readiness(True),
        staging=staging_evidence,
    )
    assert lifecycle["lifecycle_state"] != "ACTIVATED"
    assert lifecycle["activation"]["evidence"] == "unavailable"
    assert lifecycle["activation"]["exact_release_is_active"] is None
    assert lifecycle["activation_authorized"] is False
    assert lifecycle["activation_implied_by_upload_or_staging"] is False
    assert lifecycle["active_vs_staged"]["state"] == "unavailable"


def test_activation_only_from_explicit_canonical_probe():
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry(state="staged")),
        readiness=_readiness(True),
        staging=_staging(1000, True, 1000),
        active_taxonomy=Evidence.of(
            {"active_release_id": EXPECTED_SHA256}, "canonical probe"
        ),
    )
    assert lifecycle["lifecycle_state"] == "ACTIVATED"
    assert lifecycle["active_vs_staged"]["state"] == "exact_release_is_active"
    assert lifecycle["activation_authorized"] is False


def test_different_active_release_is_reported_as_divergent():
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry(state="staged")),
        readiness=_readiness(True),
        staging=_staging(1000, True, 1000),
        active_taxonomy=Evidence.of({"active_release_id": "b" * 64}, "canonical probe"),
    )
    assert lifecycle["lifecycle_state"] == "STAGED_COMPLETE"
    assert (
        lifecycle["active_vs_staged"]["state"]
        == "active_release_differs_from_exact_release"
    )
    assert lifecycle["active_vs_staged"]["active_release_id"] == "b" * 64
    assert lifecycle["active_vs_staged"]["staged_release_id"] == EXPECTED_SHA256


def test_no_active_release_is_distinct_from_unavailable():
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry()),
        active_taxonomy=Evidence.of({"active_release_id": None}, "canonical probe"),
    )
    assert lifecycle["active_vs_staged"]["state"] == "no_active_canonical_release"


# --- identity verification -----------------------------------------------------


def test_exact_identity_verifies():
    identity = verify_source_identity(_exact_entry())
    assert identity["verified"] is True
    assert identity["mismatches"] == []


def test_identity_conflict_is_reported_not_silently_accepted():
    identity = verify_source_identity(
        _exact_entry(sha256="c" * 64, size_bytes=EXPECTED_SIZE_BYTES)
    )
    assert identity["verified"] is False
    assert identity["reason"] == "identity_conflict"
    assert any(item["field"] == "sha256" for item in identity["mismatches"])


def test_missing_identity_fields_are_incomplete_not_conflicting():
    identity = verify_source_identity(
        {"release_id": EXPECTED_SHA256, "snapshot": {"filename": EXPECTED_FILENAME}}
    )
    assert identity["verified"] is False
    assert identity["reason"] == "identity_evidence_incomplete"
    assert {item["observed"] for item in identity["mismatches"]} == {"unavailable"}


def test_absent_source_identity_is_unverifiable():
    identity = verify_source_identity(None)
    assert identity["verified"] is None
    assert identity["reason"] == "unavailable"


# --- downstream relink/backfill enumeration ------------------------------------


REQUIRED_SURFACES = {
    "occurrences",
    "media",
    "traits",
    "literature",
    "interactions",
    "knowledge_graph",
}


def test_all_required_downstream_surfaces_are_enumerated():
    audit = enumerate_downstream_relink_impact(
        change_report=Evidence.unavailable("no change report")
    )
    assert set(audit["surfaces_enumerated"]) == REQUIRED_SURFACES
    assert audit["relink_execution_authorized"] is False
    assert audit["backfill_execution_authorized"] is False
    assert audit["knowledge_graph_mutation_authorized"] is False


def test_downstream_counts_without_a_probe_are_unavailable_not_zero():
    audit = enumerate_downstream_relink_impact(
        change_report=Evidence.of({"summary": {"added_taxa": 3}}, "report")
    )
    assert audit["counts_complete"] is False
    for domain in audit["domains"]:
        assert domain["affected_records"] is None
        assert domain["count_evidence"] == "unavailable"


def test_downstream_counts_are_summed_across_impact_domains_when_probed():
    audit = enumerate_downstream_relink_impact(
        change_report=Evidence.of(
            {
                "summary": {
                    "accepted_name_change_candidates": 2,
                    "removed_taxa": 1,
                    "added_taxa": 4,
                    "synonym_changes": 0,
                    "status_changes": 0,
                    "malformed_rows": 0,
                    "duplicate_identities": 0,
                }
            },
            "report",
        ),
        domain_counts=Evidence.of(
            {
                "occurrences": 10,
                "images": 5,
                "traits": 2,
                "literature": 1,
                "pollinators": 3,
                "mycorrhizae": 4,
                "knowledge_graph_edges": 7,
            },
            "read-only count probe",
        ),
    )
    by_surface = {item["surface"]: item for item in audit["domains"]}
    assert by_surface["interactions"]["affected_records"] == 7
    assert by_surface["media"]["affected_records"] == 5
    assert audit["counts_complete"] is True
    assert audit["unresolved_blockers"] == []


def test_malformed_and_duplicate_rows_surface_as_unresolved_blockers():
    audit = enumerate_downstream_relink_impact(
        change_report=Evidence.of(
            {"summary": {"malformed_rows": 12, "duplicate_identities": 3}}, "report"
        )
    )
    assert "malformed_rows_present" in audit["unresolved_blockers"]
    assert "duplicate_identities_present" in audit["unresolved_blockers"]


def test_missing_change_report_marks_blockers_unavailable_not_clean():
    audit = enumerate_downstream_relink_impact(
        change_report=Evidence.unavailable("no change report")
    )
    assert "malformed_rows_unavailable" in audit["unresolved_blockers"]
    assert audit["drivers_evidence"] == "unavailable"


# --- receipts and status projection --------------------------------------------


def test_owner_exception_receipt_never_claims_incorporation():
    lifecycle = classify_release_lifecycle(releases=_releases())
    receipt = build_owner_exception_receipt(
        lifecycle=lifecycle,
        blocking_reason="production intake write requires owner authorization",
        next_executable_action="run the guarded upload client with --execute",
        responsible_party="repository owner",
        prepared_action={"script": "scripts/upload_hassler_release_guarded.py"},
    )
    assert receipt["action_executed"] is False
    assert receipt["upload_invoked"] is False
    assert receipt["staging_invoked"] is False
    assert receipt["production_mutation"] is False
    assert receipt["incorporation_assumed"] is False
    assert receipt["action_validated"] is True
    assert receipt["lifecycle_state"] == "ABSENT"
    assert len(receipt["artifact_hash"]) == 64


def test_owner_exception_receipt_hash_is_deterministic():
    lifecycle = classify_release_lifecycle(releases=_releases())
    kwargs = {
        "lifecycle": lifecycle,
        "blocking_reason": "reason",
        "next_executable_action": "action",
        "responsible_party": "repository owner",
    }
    assert (
        build_owner_exception_receipt(**kwargs)["artifact_hash"]
        == build_owner_exception_receipt(**kwargs)["artifact_hash"]
    )


def test_status_block_exposes_release_identity_and_active_vs_staged():
    lifecycle = classify_release_lifecycle(
        releases=_releases(_exact_entry(state="staged")),
        readiness=_readiness(True),
        staging=_staging(1000, True, 1000, change_report={"summary": {}}),
    )
    downstream = enumerate_downstream_relink_impact(
        change_report=Evidence.of({"summary": {}}, "report")
    )
    block = build_release_status_block(lifecycle=lifecycle, downstream=downstream)
    assert block["release_identity"]["sha256"] == EXPECTED_SHA256
    assert block["release_identity"]["filename"] == EXPECTED_FILENAME
    assert block["lifecycle_state"] == "STAGED_COMPLETE"
    assert block["staged_release_id"] == EXPECTED_SHA256
    assert block["active_release_id"] is None
    assert block["active_vs_staged"] == "unavailable"
    assert block["taxonomy_activation"] == "separately_protected_owner_gate"
    assert block["activation_implied_by_upload_or_staging"] is False
    assert set(block["downstream_relink_surfaces"]) == REQUIRED_SURFACES
    assert len(block["artifact_hash"]) == 64
