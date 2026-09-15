"""CALYX Gate 2 — deterministic fake executor tests.

Acceptance criteria (from issue #1187 Gate 2):
- One request claimed exactly once (idempotent).
- Duplicate/replayed execution does not duplicate project or artifacts.
- State transitions are durable and ordered.
- Blocked state records a bounded blocker code.
- Completed state records immutable result artifact IDs.
- Retry/restart resumes safely.
- No request remains stuck in RUNNING/LEASED after terminal completion.
- No scientific publication/KG/taxonomy mutation occurs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.calyx_orchestrator.artifact_registry import ImmutableArtifactRegistry
from runtime.calyx_research_executor import (
    TRANSITION_MAP,
    TERMINAL_STATES,
    VALID_BLOCKER_CODES,
    CalyxResearchExecutorService,
    ExecutionResult,
    _project_id_for,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_request(
    *,
    request_id: str = "RSR-GH-TEST001",
    status: str = "queued_waiting_for_executor",
) -> dict:
    return {
        "id": request_id,
        "title": "Five orchid genera investigation",
        "research_question": (
            "What is known about thermal regulation in *Calypso bulbosa*?"
        ),
        "taxa": ["Calypso bulbosa"],
        "priority": "medium",
        "owner": "calyx_executor",
        "status": status,
        "provenance": {
            "integration": "calyx-github-research-bridge/v1",
            "source_repository": "jsp1440/Orchid-Continuum-Brain",
            "source_issue_number": 101,
            "source_issue_url": (
                "https://github.com/jsp1440/Orchid-Continuum-Brain/issues/101"
            ),
        },
        "status_history": [],
    }


def _executor(
    requests: list | None = None,
    workspace: Path | None = None,
) -> tuple[CalyxResearchExecutorService, list, list, ImmutableArtifactRegistry]:
    mem_requests: list = requests if requests is not None else []
    mem_projects: list = []
    registry = ImmutableArtifactRegistry()
    svc = CalyxResearchExecutorService(
        memory_requests=mem_requests,
        memory_projects=mem_projects,
        artifact_registry=registry,
        github_feedback_fn=None,  # no live GitHub calls
        station_workspace=workspace,
    )
    return svc, mem_requests, mem_projects, registry


# ── State machine transition table ───────────────────────────────────────────


def test_transition_map_is_complete():
    assert "queued_waiting_for_executor" in TRANSITION_MAP
    assert "queued" in TRANSITION_MAP
    assert "running" in TRANSITION_MAP
    all_targets: set[str] = set()
    for targets in TRANSITION_MAP.values():
        all_targets.update(targets)
    assert "completed" in all_targets
    assert "blocked" in all_targets


def test_terminal_states_are_correct():
    assert "completed" in TERMINAL_STATES
    assert "blocked" in TERMINAL_STATES
    assert "running" not in TERMINAL_STATES
    assert "queued" not in TERMINAL_STATES


def test_blocker_codes_are_bounded():
    assert VALID_BLOCKER_CODES
    assert "NO_EXECUTOR_AVAILABLE" in VALID_BLOCKER_CODES
    for code in VALID_BLOCKER_CODES:
        assert code.isupper(), f"Blocker code must be UPPER_SNAKE: {code}"


# ── Claim (idempotent, exactly-once) ─────────────────────────────────────────


def test_claim_transitions_from_queued_waiting(tmp_path):
    req = _make_request()
    svc, mem_req, _, _ = _executor([req], workspace=tmp_path)
    result = svc.claim("RSR-GH-TEST001")
    assert result["status"] == "queued"
    assert len(result["status_history"]) == 1
    entry = result["status_history"][0]
    assert entry["from_state"] == "queued_waiting_for_executor"
    assert entry["to_state"] == "queued"


def test_claim_is_idempotent_when_already_queued(tmp_path):
    req = _make_request(status="queued")
    svc, _, _, _ = _executor([req], workspace=tmp_path)
    result1 = svc.claim("RSR-GH-TEST001")
    result2 = svc.claim("RSR-GH-TEST001")
    assert result1["status"] == "queued"
    assert result2["status"] == "queued"


def test_claim_is_idempotent_when_already_running(tmp_path):
    req = _make_request(status="running")
    req["research_project_id"] = _project_id_for("RSR-GH-TEST001")
    svc, _, _, _ = _executor([req], workspace=tmp_path)
    result = svc.claim("RSR-GH-TEST001")
    assert result["status"] == "running"


def test_claim_is_idempotent_when_completed(tmp_path):
    req = _make_request(status="completed")
    req["result_artifact_ids"] = ["art-001"]
    svc, _, _, _ = _executor([req], workspace=tmp_path)
    result = svc.claim("RSR-GH-TEST001")
    assert result["status"] == "completed"


def test_claim_raises_for_unknown_request(tmp_path):
    svc, _, _, _ = _executor([], workspace=tmp_path)
    with pytest.raises(LookupError, match="RESEARCH_REQUEST_NOT_FOUND"):
        svc.claim("RSR-GH-MISSING")


# ── Start running and project binding ────────────────────────────────────────


def test_start_running_transitions_queued_to_running(tmp_path):
    req = _make_request(status="queued")
    svc, mem_req, mem_proj, _ = _executor([req], workspace=tmp_path)
    result = svc.start_running("RSR-GH-TEST001")
    assert result["status"] == "running"
    assert result.get("research_project_id")


def test_start_running_persists_project(tmp_path):
    req = _make_request(status="queued")
    svc, _, mem_proj, _ = _executor([req], workspace=tmp_path)
    svc.start_running("RSR-GH-TEST001")
    assert len(mem_proj) == 1
    project = mem_proj[0]["payload"]
    assert project["request_id"] == "RSR-GH-TEST001"
    assert project["scientific_publication_authorized"] is False
    assert project["knowledge_graph_mutation_authorized"] is False
    assert project["taxonomy_activation_authorized"] is False


def test_start_running_is_idempotent_when_already_running(tmp_path):
    req = _make_request(status="running")
    req["research_project_id"] = _project_id_for("RSR-GH-TEST001")
    svc, _, mem_proj, _ = _executor([req], workspace=tmp_path)
    result = svc.start_running("RSR-GH-TEST001")
    assert result["status"] == "running"
    assert len(mem_proj) == 0  # no new project created (already running)


def test_start_running_raises_for_wrong_state(tmp_path):
    req = _make_request(status="queued_waiting_for_executor")
    svc, _, _, _ = _executor([req], workspace=tmp_path)
    with pytest.raises(ValueError, match="RESEARCH_REQUEST_STATE_INVALID"):
        svc.start_running("RSR-GH-TEST001")


# ── Complete ──────────────────────────────────────────────────────────────────


def test_complete_transitions_running_to_completed(tmp_path):
    req = _make_request(status="running")
    svc, mem_req, _, _ = _executor([req], workspace=tmp_path)
    result = svc.complete(
        "RSR-GH-TEST001",
        artifact_ids=["calyx-result-art001"],
        notes="Test run.",
    )
    assert result["status"] == "completed"
    assert result["result_artifact_ids"] == ["calyx-result-art001"]
    assert result["blocker"] is None


def test_complete_is_idempotent(tmp_path):
    req = _make_request(status="completed")
    req["result_artifact_ids"] = ["art-001"]
    svc, _, _, _ = _executor([req], workspace=tmp_path)
    result = svc.complete("RSR-GH-TEST001", artifact_ids=["art-002"])
    assert result["status"] == "completed"
    # Idempotent: original artifact IDs preserved
    assert "art-001" in result.get("result_artifact_ids", [])


def test_complete_raises_for_wrong_state(tmp_path):
    req = _make_request(status="queued")
    svc, _, _, _ = _executor([req], workspace=tmp_path)
    with pytest.raises(ValueError, match="RESEARCH_REQUEST_STATE_INVALID"):
        svc.complete("RSR-GH-TEST001", artifact_ids=[])


# ── Block ─────────────────────────────────────────────────────────────────────


def test_block_transitions_running_to_blocked(tmp_path):
    req = _make_request(status="running")
    svc, _, _, _ = _executor([req], workspace=tmp_path)
    result = svc.block(
        "RSR-GH-TEST001",
        code="NO_EXECUTOR_AVAILABLE",
        detail="Fake executor stubbed out.",
    )
    assert result["status"] == "blocked"
    assert isinstance(result["blocker"], dict)
    assert result["blocker"]["code"] == "NO_EXECUTOR_AVAILABLE"


def test_block_rejects_invalid_blocker_code(tmp_path):
    req = _make_request(status="running")
    svc, _, _, _ = _executor([req], workspace=tmp_path)
    with pytest.raises(ValueError, match="INVALID_BLOCKER_CODE"):
        svc.block("RSR-GH-TEST001", code="MADE_UP_CODE")


def test_block_is_idempotent(tmp_path):
    req = _make_request(status="blocked")
    req["blocker"] = {"code": "TIMEOUT", "detail": "", "at": "2026-09-01T00:00:00"}
    svc, _, _, _ = _executor([req], workspace=tmp_path)
    result = svc.block("RSR-GH-TEST001", code="NO_EXECUTOR_AVAILABLE")
    assert result["status"] == "blocked"
    assert result["blocker"]["code"] == "TIMEOUT"  # original preserved


def test_block_raises_for_wrong_state(tmp_path):
    req = _make_request(status="queued")
    svc, _, _, _ = _executor([req], workspace=tmp_path)
    with pytest.raises(ValueError, match="RESEARCH_REQUEST_STATE_INVALID"):
        svc.block("RSR-GH-TEST001", code="TIMEOUT")


# ── Full fake execution (Gate 2 acceptance) ───────────────────────────────────


def test_fake_executor_completes_full_state_machine(tmp_path):
    req = _make_request()
    svc, mem_req, mem_proj, registry = _executor([req], workspace=tmp_path)
    result: ExecutionResult = svc.execute_fake("RSR-GH-TEST001")

    assert result.final_state == "completed"
    assert result.blocker_code is None
    assert len(result.artifact_ids) == 1

    # Verify artifact was registered in the registry.
    artifact = registry.require(result.artifact_ids[0])
    assert artifact.artifact_id == result.artifact_ids[0]
    assert artifact.media_type == "application/json"
    assert artifact.evidence_uris  # at least one evidence URI

    # Verify checksum is a valid SHA-256 hex string.
    assert len(artifact.checksum) == 64
    assert all(c in "0123456789abcdef" for c in artifact.checksum)

    # Verify project was created and bound.
    assert result.project_id
    assert len(mem_proj) == 1
    proj = mem_proj[0]["payload"]
    assert proj["request_id"] == "RSR-GH-TEST001"

    # Verify the final request state in memory.
    final_req = next(
        (r for r in mem_req if (r.get("payload") or r).get("id") == "RSR-GH-TEST001"),
        None,
    )
    assert final_req is not None
    record = final_req.get("payload") if isinstance(final_req.get("payload"), dict) else final_req
    assert record["status"] == "completed"
    assert record["result_artifact_ids"] == [result.artifact_ids[0]]


def test_fake_executor_full_state_history_is_ordered(tmp_path):
    req = _make_request()
    svc, mem_req, _, _ = _executor([req], workspace=tmp_path)
    result = svc.execute_fake("RSR-GH-TEST001")

    history = result.status_history
    states = [(e["from_state"], e["to_state"]) for e in history]
    assert states[0] == ("queued_waiting_for_executor", "queued")
    assert states[1] == ("queued", "running")
    assert states[2] == ("running", "completed")


def test_duplicate_execution_does_not_duplicate_project_or_artifacts(tmp_path):
    req = _make_request()
    svc, mem_req, mem_proj, registry = _executor([req], workspace=tmp_path)

    result1 = svc.execute_fake("RSR-GH-TEST001")
    result2 = svc.execute_fake("RSR-GH-TEST001")

    # Same artifact ID both times.
    assert result1.artifact_ids == result2.artifact_ids

    # Only one project in memory.
    assert len(mem_proj) == 1

    # Registry does not duplicate artifacts.
    assert len(registry.discover()) == 1


def test_no_request_stuck_in_running_after_completion(tmp_path):
    req = _make_request()
    svc, mem_req, _, _ = _executor([req], workspace=tmp_path)
    svc.execute_fake("RSR-GH-TEST001")

    record = next(
        (
            r.get("payload") if isinstance(r.get("payload"), dict) else r
            for r in mem_req
            if (r.get("payload") or r).get("id") == "RSR-GH-TEST001"
        ),
        None,
    )
    assert record is not None
    assert record["status"] not in {"running", "queued"}


# ── Governance / no mutation assertions ──────────────────────────────────────


def test_governance_flags_in_project_are_false(tmp_path):
    req = _make_request(status="queued")
    svc, _, mem_proj, _ = _executor([req], workspace=tmp_path)
    svc.start_running("RSR-GH-TEST001")
    proj = mem_proj[0]["payload"]
    assert proj["scientific_publication_authorized"] is False
    assert proj["knowledge_graph_mutation_authorized"] is False
    assert proj["taxonomy_activation_authorized"] is False
    assert proj["production_deployment_authorized"] is False


def test_artifact_content_carries_no_publication_authority(tmp_path):
    req = _make_request()
    svc, _, _, registry = _executor([req], workspace=tmp_path)
    result = svc.execute_fake("RSR-GH-TEST001")
    artifact = registry.require(result.artifact_ids[0])
    # ArtifactRecord does not expose raw content; verify governance through
    # source_uri scheme and the executor's known authority constraints.
    assert artifact.source_uri.startswith("calyx://research-executor/fake/")
    # The artifact is not evidence of publication authority — it is bound to a
    # specific request and carries research provenance only.
    assert artifact.producer_assignment_id == "RSR-GH-TEST001"
    assert any(
        uri.startswith("calyx://research-request/")
        for uri in artifact.evidence_uris
    )


# ── Retry / restart safety ────────────────────────────────────────────────────


def test_retry_from_queued_waiting_resumes_safely(tmp_path):
    req = _make_request()
    svc, mem_req, mem_proj, registry = _executor([req], workspace=tmp_path)
    result = svc.execute_fake("RSR-GH-TEST001")
    assert result.final_state == "completed"
    pre_restart_artifacts = list(result.artifact_ids)

    # Simulate a restart: rebuild executor with same backing stores.
    svc2 = CalyxResearchExecutorService(
        memory_requests=mem_req,
        memory_projects=mem_proj,
        artifact_registry=registry,
        station_workspace=tmp_path,
    )
    result2 = svc2.execute_fake("RSR-GH-TEST001")
    assert result2.final_state == "completed"
    assert result2.artifact_ids == pre_restart_artifacts


def test_blocked_state_records_bounded_code_and_detail(tmp_path):
    req = _make_request()
    svc, _, _, _ = _executor([req], workspace=tmp_path)
    svc.claim("RSR-GH-TEST001")
    svc.start_running("RSR-GH-TEST001")
    result_dict = svc.block(
        "RSR-GH-TEST001",
        code="PROVIDER_UNAVAILABLE",
        detail="EuropePMC timed out.",
    )
    assert result_dict["status"] == "blocked"
    blocker = result_dict["blocker"]
    assert blocker["code"] == "PROVIDER_UNAVAILABLE"
    assert "EuropePMC timed out" in blocker["detail"]
    assert blocker["code"] in VALID_BLOCKER_CODES
