"""Deterministic tests for the evidence_readiness_evaluation mission handler (#1732)."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from app.missions.evidence_readiness import (
    MAX_CANDIDATES,
    build_evidence_readiness_report,
)
from app.missions.registry import MISSION_TYPES
from app.missions.repositories import InMemoryMissionRepository
from app.missions.services import MissionService

PROVENANCE = {"document_id": "doc-1", "extractor": "fixture"}


def entity(candidate_id: int, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "candidate_id": candidate_id,
        "kind": "ENTITY",
        "candidate_review_status": "ACCEPTED",
        "session_stage": "READY_FOR_REVIEW",
        "candidate_provenance": PROVENANCE,
        "resolution_status": "ACCEPTED",
        "registry_status": "ACTIVE",
    }
    data.update(overrides)
    return data


def relationship(candidate_id: int, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "candidate_id": candidate_id,
        "kind": "RELATIONSHIP",
        "candidate_review_status": "ACCEPTED",
        "session_stage": "READY_FOR_REVIEW",
        "candidate_provenance": PROVENANCE,
        "evidence_validation_status": "VALID",
        "subject_ready": True,
        "object_ready": True,
    }
    data.update(overrides)
    return data


def manifest(*candidates: dict[str, Any]) -> dict[str, Any]:
    return {"source": "fixture-session-7", "candidates": list(candidates)}


def by_id(report: dict[str, Any]) -> dict[Any, dict[str, Any]]:
    return {item["candidate_id"]: item for item in report["evaluations"]}


def mission_payload(input_manifest: dict[str, Any], key: str) -> dict[str, Any]:
    return {
        "mission_key": key,
        "title": "Evidence readiness",
        "description": "Report candidate readiness for human review.",
        "mission_type": "evidence_readiness_evaluation",
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
    }


def run_mission(input_manifest: dict[str, Any], key: str) -> tuple[MissionService, int]:
    service = MissionService(InMemoryMissionRepository())
    mission = service.create(
        mission_payload(input_manifest, key), {"auth_type": "owner_session"}
    )
    mission_id = mission["mission_id"]
    service.submit(mission_id, "owner", "ready")
    service.approve(mission_id, "owner", "approve", "approval-1732")
    service.queue(mission_id, "owner", "queue")
    service.execute_cycle("worker-readiness")
    return service, mission_id


def test_registry_contract_preserves_limits():
    mission_type = MISSION_TYPES["evidence_readiness_evaluation"]
    assert mission_type.handler == "evidence_readiness_evaluation"
    assert mission_type.risk_level == "medium"
    assert mission_type.write_scope == "read_only"
    assert mission_type.allowed_database_schemas == ("oc_ontology",)
    assert "oc_taxonomy" in mission_type.forbidden_database_schemas
    assert mission_type.human_approval_required is True
    assert mission_type.publication_authority_required is False
    assert mission_type.canonical_graph_writes_permitted is False
    assert mission_type.taxonomy_writes_prohibited is True


def test_report_is_human_review_only_and_asserts_no_authority():
    report = build_evidence_readiness_report(manifest(entity(1), relationship(2)))

    assert report["review_state"] == "awaiting_human_review"
    assert report["human_review_required"] is True
    assert report["scientific_authority"] == "none"
    for flag in (
        "scientific_conclusions_published",
        "approval_recorded",
        "evidence_state_changed",
        "readiness_persisted",
        "provider_called",
        "external_network_called",
        "domain_database_written",
        "canonical_graph_mutated",
        "taxonomy_mutated",
    ):
        assert report[flag] is False, flag
    assert "ready_for_publication" not in str(report)
    for item in report["evaluations"]:
        assert item["readiness_state"] == "CRITERIA_MET_AWAITING_HUMAN_REVIEW"
        assert item["human_review_required"] is True
        assert item["blockers"] == []
        assert item["missing_fields"] == []


def test_blockers_mirror_publication_readiness_rules():
    report = build_evidence_readiness_report(
        manifest(
            entity(1, candidate_review_status="PENDING"),
            entity(2, session_stage="CANDIDATE_GENERATION"),
            entity(3, candidate_provenance={}),
            entity(4, resolution_status="UNRESOLVED"),
            entity(5, resolution_status="NEEDS_REVIEW"),
            entity(6, registry_status="DEPRECATED"),
            relationship(7, subject_ready=False, object_ready=False),
        )
    )
    results = by_id(report)
    assert results[1]["blockers"] == ["CANDIDATE_NOT_ACCEPTED"]
    assert results[1]["criteria"]["review"]["observed"] == "PENDING"
    assert results[2]["blockers"] == ["SESSION_NOT_READY_FOR_REVIEW"]
    assert results[3]["blockers"] == ["PROVENANCE_INCOMPLETE"]
    assert results[4]["blockers"] == ["ONTOLOGY_UNRESOLVED"]
    assert results[5]["blockers"] == ["ONTOLOGY_MATCH_NOT_ACCEPTED"]
    assert results[6]["blockers"] == ["ONTOLOGY_VERSION_INACTIVE"]
    assert results[7]["blockers"] == ["SUBJECT_NOT_READY", "OBJECT_NOT_READY"]
    assert all(item["readiness_state"] == "BLOCKED" for item in results.values())
    assert report["summary"]["readiness_state_counts"]["BLOCKED"] == 7


def test_evidence_states_stay_distinct():
    report = build_evidence_readiness_report(
        manifest(
            relationship(1, evidence_validation_status="PENDING"),
            relationship(2, evidence_validation_status="INVALID"),
            relationship(3, evidence_validation_status="SUPERSEDED"),
            relationship(4, evidence_validation_status="ABSENT"),
        )
    )
    results = by_id(report)
    assert [results[i]["blockers"] for i in (1, 2, 3, 4)] == [
        ["EVIDENCE_PENDING_VALIDATION"],
        ["EVIDENCE_INVALID"],
        ["EVIDENCE_SUPERSEDED"],
        ["EVIDENCE_MISSING"],
    ]
    assert [results[i]["criteria"]["evidence"]["observed"] for i in (1, 2, 3, 4)] == [
        "PENDING",
        "INVALID",
        "SUPERSEDED",
        "ABSENT",
    ]


def test_unsupplied_inputs_are_unknown_not_satisfied():
    report = build_evidence_readiness_report(
        manifest(
            {"candidate_id": 1, "kind": "ENTITY"},
            {
                "candidate_id": "rel-2",
                "kind": "RELATIONSHIP",
                "candidate_review_status": "ACCEPTED",
            },
            entity(3, registry_status=None),
        )
    )
    results = by_id(report)
    assert results[1]["readiness_state"] == "INDETERMINATE"
    assert results[1]["blockers"] == []
    assert results[1]["missing_fields"] == [
        "candidate_review_status",
        "session_stage",
        "candidate_provenance",
        "resolution_status",
    ]
    assert results["rel-2"]["readiness_state"] == "INDETERMINATE"
    assert results["rel-2"]["unknown_criteria"] == [
        "evidence",
        "object",
        "provenance",
        "session",
        "subject",
    ]
    assert results[3]["readiness_state"] == "INDETERMINATE"
    assert results[3]["missing_fields"] == ["registry_status"]
    # A known blocker dominates unknown inputs; unknowns are still reported.
    mixed = by_id(
        build_evidence_readiness_report(
            manifest(
                {
                    "candidate_id": 9,
                    "kind": "ENTITY",
                    "candidate_review_status": "REJECTED",
                }
            )
        )
    )
    assert mixed[9]["readiness_state"] == "BLOCKED"
    assert "session_stage" in mixed[9]["missing_fields"]
    counts = report["summary"]["readiness_state_counts"]
    assert counts == {
        "BLOCKED": 0,
        "INDETERMINATE": 3,
        "CRITERIA_MET_AWAITING_HUMAN_REVIEW": 0,
    }


def test_report_is_deterministic_and_does_not_mutate_input():
    original = manifest(
        entity(1), relationship(2, evidence_validation_status="PENDING")
    )
    snapshot = copy.deepcopy(original)
    first = build_evidence_readiness_report(original)
    second = build_evidence_readiness_report(copy.deepcopy(original))
    assert first == second
    assert len(first["report_digest"]) == 64
    assert original == snapshot


@pytest.mark.parametrize(
    "bad_manifest",
    [
        {},
        [],
        {"source": "", "candidates": [{"candidate_id": 1, "kind": "ENTITY"}]},
        {"source": "s", "candidates": []},
        {"source": "s", "candidates": "not-a-list"},
        {"source": "s", "candidates": [1]},
        {
            "source": "s",
            "candidates": [{"candidate_id": 1, "kind": "ENTITY"}],
            "publish": True,
        },
        {"source": "s", "candidates": [{"candidate_id": 1, "kind": "CLAIM"}]},
        {"source": "s", "candidates": [{"kind": "ENTITY"}]},
        {"source": "s", "candidates": [{"candidate_id": True, "kind": "ENTITY"}]},
        {"source": "s", "candidates": [{"candidate_id": 0, "kind": "ENTITY"}]},
        {"source": "s", "candidates": [entity(1), entity(1)]},
        {"source": "s", "candidates": [entity(1, ready_for_publication=True)]},
        {"source": "s", "candidates": [entity(1, evidence_validation_status="VALID")]},
        {"source": "s", "candidates": [relationship(1, resolution_status="ACCEPTED")]},
        {"source": "s", "candidates": [entity(1, candidate_review_status="APPROVED")]},
        {"source": "s", "candidates": [entity(1, resolution_status="accepted")]},
        {
            "source": "s",
            "candidates": [relationship(1, evidence_validation_status="VERIFIED")],
        },
        {"source": "s", "candidates": [relationship(1, subject_ready="yes")]},
        {"source": "s", "candidates": [entity(1, candidate_provenance="doc-1")]},
        {
            "source": "s",
            "candidates": [entity(i + 1) for i in range(MAX_CANDIDATES + 1)],
        },
    ],
)
def test_out_of_contract_manifest_fails_closed(bad_manifest: Any):
    with pytest.raises(ValueError, match="EVIDENCE_READINESS_MANIFEST_INVALID"):
        build_evidence_readiness_report(bad_manifest)


def test_mission_lifecycle_completes_with_review_report():
    service, mission_id = run_mission(
        manifest(entity(1), relationship(2)), key="readiness-1"
    )

    completed = service.get(mission_id)
    assert completed["state"] == "completed"
    output = completed["output_manifest"]
    assert output["artifact_type"] == "evidence_readiness_report"
    assert output["review_state"] == "awaiting_human_review"
    assert output["canonical_graph_mutated"] is False
    assert output["taxonomy_mutated"] is False
    assert service.jobs(mission_id)[0]["state"] == "succeeded"


def test_mission_with_invalid_manifest_fails_and_does_not_complete():
    service, mission_id = run_mission(
        {"source": "s", "candidates": []}, key="readiness-bad"
    )

    mission = service.get(mission_id)
    assert mission["state"] != "completed"
    assert mission["output_manifest"] == {}
    assert "EVIDENCE_READINESS_MANIFEST_INVALID" in mission["last_error"]


def test_handler_module_has_no_provider_network_or_db_imports():
    source = Path("app/missions/evidence_readiness.py").read_text(encoding="utf-8")
    for token in (
        "anthropic",
        "openai",
        "requests",
        "httpx",
        "urllib",
        "psycopg",
        "subprocess",
        "socket",
        "app.ontology",
        "repository",
    ):
        assert token not in source.replace(
            "app.ontology.services.PublicationReadinessService", ""
        ), token
