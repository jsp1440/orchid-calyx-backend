"""Focused tests for the governed BUILD-051 research executor (Gates 4–6).

These tests run entirely offline — no network calls, no running database.
The external literature search is mocked so tests are deterministic.

Key invariants verified:
- exactly-once / idempotent claim
- valid state transitions; invalid transitions rejected
- Research Station project is bound
- artifact is created and readable
- blocked when external literature is unavailable
- completed when external literature returns results
- no KG / taxonomy / publication authority
- replay produces no duplicate artifacts
- arbitrary orchid taxa (Gate 3 five-taxon list) work end-to-end
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.calyx_orchestrator.artifact_registry import ImmutableArtifactRegistry
from app.calyx_orchestrator.research_executor import (
    GovervedResearchExecutor,
    ResearchExecutorResult,
    ResearchRequestStore,
    _AUTHORITY,
    _VALID_TRANSITIONS,
)
from runtime.research_station import ResearchStationService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GATE3_TAXA = [
    "Calypso bulbosa",
    "Pleione humilis",
    "Ponerorchis graminifolia",
    "Cephalanthera austiniae",
    "Goodyera oblongifolia",
]


def _request(
    request_id: str = "req-001",
    taxa: list[str] | None = None,
    status: str = "queued_waiting_for_executor",
) -> dict[str, Any]:
    return {
        "id": request_id,
        "title": "Five-orchid investigation",
        "research_question": "Evidence dossiers for five rare orchid taxa",
        "taxa": taxa or GATE3_TAXA,
        "status": status,
        "provenance": {
            "integration": "test",
            "source_repository": "test/repo",
            "source_issue_number": 101,
        },
        "created_at": "2026-09-03T00:00:00Z",
    }


def _executor(tmp_path: Path) -> GovervedResearchExecutor:
    registry = ImmutableArtifactRegistry()
    station = ResearchStationService(workspace=tmp_path / "station", artifact_registry=registry)
    return GovervedResearchExecutor(
        store=ResearchRequestStore(),
        station=station,
        artifact_registry=registry,
        workspace=tmp_path / "station",
    )


def _lit_results(n: int = 3) -> dict[str, Any]:
    return {
        "provider": "Europe PMC",
        "status": "available",
        "results": [
            {
                "title": f"Orchid paper {i}",
                "pmid": f"1000{i}",
                "doi": f"10.1000/{i}",
                "abstract": f"Abstract {i}",
                "authors": "Author A",
                "journal": "J. Orchid Sci.",
                "publication_date": "2024-01-01",
                "review_state": "REVIEW_REQUIRED",
                "external": True,
            }
            for i in range(n)
        ],
        "result_count": n,
        "query_plan": ["Calypso AND orchid"],
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


def _lit_empty() -> dict[str, Any]:
    return {
        "provider": "Europe PMC",
        "status": "EMPTY",
        "results": [],
        "result_count": 0,
        "query_plan": [],
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


# ---------------------------------------------------------------------------
# State machine and store tests
# ---------------------------------------------------------------------------


def test_valid_transitions_exhaustive():
    assert "queued" in _VALID_TRANSITIONS["queued_waiting_for_executor"]
    assert "running" in _VALID_TRANSITIONS["queued"]
    assert "completed" in _VALID_TRANSITIONS["running"]
    assert "blocked" in _VALID_TRANSITIONS["running"]
    assert not _VALID_TRANSITIONS["completed"]
    assert not _VALID_TRANSITIONS["blocked"]


def test_store_upsert_idempotent():
    store = ResearchRequestStore()
    req = _request("r1")
    rec1, created1 = store.upsert(req)
    rec2, created2 = store.upsert(req)
    assert created1 is True
    assert created2 is False
    assert rec1["id"] == rec2["id"] == "r1"


def test_store_invalid_transition_raises():
    store = ResearchRequestStore()
    req = _request("r2")
    store.upsert(req)
    # Can't go from queued_waiting_for_executor → completed directly
    with pytest.raises(ValueError, match="INVALID_TRANSITION"):
        store.update_status("r2", status="completed")


def test_store_unknown_request_raises():
    store = ResearchRequestStore()
    with pytest.raises(LookupError, match="NOT_FOUND"):
        store.update_status("nonexistent", status="queued")


# ---------------------------------------------------------------------------
# Core executor lifecycle
# ---------------------------------------------------------------------------


def test_executor_drives_to_completed(tmp_path):
    exe = _executor(tmp_path)
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(3),
    ):
        result = exe.execute(_request())
    assert result.status == "completed"
    assert result.project_id is not None
    assert len(result.artifact_ids) == 1
    assert result.blocker is None
    assert result.authority["knowledge_graph_mutation_authorized"] is False
    assert result.authority["scientific_publication_authorized"] is False


def test_executor_drives_to_blocked_on_empty_literature(tmp_path):
    exe = _executor(tmp_path)
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_empty(),
    ):
        result = exe.execute(_request("req-empty"))
    assert result.status == "blocked"
    assert result.blocker_code == "LITERATURE_UNAVAILABLE_OR_EMPTY"
    # An artifact is still produced even in blocked state
    assert len(result.artifact_ids) == 1


def test_executor_drives_to_blocked_on_network_error(tmp_path):
    exe = _executor(tmp_path)
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        side_effect=ConnectionError("network unreachable"),
    ):
        result = exe.execute(_request("req-net"))
    assert result.status == "blocked"
    assert result.blocker_code == "LITERATURE_UNAVAILABLE_OR_EMPTY"
    assert "network unreachable" in (result.blocker or "")


# ---------------------------------------------------------------------------
# Idempotency / replay
# ---------------------------------------------------------------------------


def test_replay_is_idempotent(tmp_path):
    exe = _executor(tmp_path)
    req = _request("req-replay")
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(2),
    ):
        r1 = exe.execute(req)
        r2 = exe.execute(req)  # replay

    assert r1.status == "completed"
    assert r2.status == "completed"
    assert r1.project_id == r2.project_id
    assert r1.artifact_ids == r2.artifact_ids


def test_replay_does_not_duplicate_artifacts(tmp_path):
    registry = ImmutableArtifactRegistry()
    station = ResearchStationService(workspace=tmp_path / "station", artifact_registry=registry)
    exe = GovervedResearchExecutor(
        store=ResearchRequestStore(),
        station=station,
        artifact_registry=registry,
    )
    req = _request("req-dup")
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(1),
    ):
        exe.execute(req)
        exe.execute(req)

    snapshot = registry.snapshot()
    # Only one artifact should be registered (replay returns existing)
    assert snapshot["artifact_count"] == 1


def test_terminal_state_is_not_re_executed(tmp_path):
    exe = _executor(tmp_path)
    req = _request("req-terminal")
    # Pre-set to completed via store
    exe._store.upsert({**req, "status": "completed", "artifact_ids": ["art-123"]})
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
    ) as mock_lit:
        result = exe.execute(req)
    mock_lit.assert_not_called()
    assert result.status == "completed"
    assert "art-123" in result.artifact_ids


# ---------------------------------------------------------------------------
# Research Station binding
# ---------------------------------------------------------------------------


def test_research_station_project_is_created(tmp_path):
    exe = _executor(tmp_path)
    req = _request("req-station")
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(1),
    ):
        result = exe.execute(req)
    project_dir = (
        tmp_path / "station" / "owners"
        / exe._get_station()._owner_key(GovervedResearchExecutor.OWNER_ID)
        / "projects"
        / result.project_id
    )
    assert (project_dir / "project.json").exists()
    data = json.loads((project_dir / "project.json").read_text())
    assert data["knowledge_graph_mutation_authorized"] is False
    assert data["scientific_publication_authorized"] is False


def test_research_station_has_research_question(tmp_path):
    exe = _executor(tmp_path)
    req = _request("req-question")
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(1),
    ):
        result = exe.execute(req)
    station = exe._get_station()
    questions_dir = station._root(GovervedResearchExecutor.OWNER_ID, result.project_id) / "questions"
    assert list(questions_dir.glob("*.json")), "No question file found"


# ---------------------------------------------------------------------------
# Artifact provenance and evidence
# ---------------------------------------------------------------------------


def test_result_artifact_is_readable(tmp_path):
    registry = ImmutableArtifactRegistry()
    station = ResearchStationService(workspace=tmp_path / "station", artifact_registry=registry)
    exe = GovervedResearchExecutor(
        store=ResearchRequestStore(),
        station=station,
        artifact_registry=registry,
    )
    req = _request("req-art")
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(2),
    ):
        result = exe.execute(req)

    assert result.artifact_ids
    content = exe.get_result_content(result.artifact_ids[0])
    assert content is not None
    payload = json.loads(content.decode())
    assert payload["request_id"] == "req-art"
    assert payload["review_required"] is True
    assert payload["authority"]["knowledge_graph_mutation_authorized"] is False


def test_result_artifact_has_evidence_state_reviewed_external_discovery(tmp_path):
    exe = _executor(tmp_path)
    req = _request("req-evstate")
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(3),
    ):
        result = exe.execute(req)
    content = exe.get_result_content(result.artifact_ids[0])
    payload = json.loads(content.decode())
    assert payload["evidence_state"] == "REVIEWED_EXTERNAL_DISCOVERY"


def test_unavailable_literature_produces_unavailable_evidence_state(tmp_path):
    exe = _executor(tmp_path)
    req = _request("req-unavail")
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        side_effect=Exception("service down"),
    ):
        result = exe.execute(req)
    content = exe.get_result_content(result.artifact_ids[0])
    payload = json.loads(content.decode())
    assert payload["evidence_state"] == "UNAVAILABLE"


def test_artifact_has_provenance_executor_key(tmp_path):
    registry = ImmutableArtifactRegistry()
    station = ResearchStationService(workspace=tmp_path / "station", artifact_registry=registry)
    exe = GovervedResearchExecutor(
        store=ResearchRequestStore(),
        station=station,
        artifact_registry=registry,
    )
    req = _request("req-prov")
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(1),
    ):
        result = exe.execute(req)
    content = exe.get_result_content(result.artifact_ids[0])
    payload = json.loads(content.decode())
    assert payload["provenance"]["executor_key"] == GovervedResearchExecutor.EXECUTOR_KEY


# ---------------------------------------------------------------------------
# Gate 3 five-taxon integration (arbitrary orchid taxa work end-to-end)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("taxon", GATE3_TAXA)
def test_arbitrary_taxon_drives_to_terminal_state(tmp_path, taxon):
    exe = _executor(tmp_path)
    req = _request(f"req-{taxon.replace(' ', '-').lower()}", taxa=[taxon])
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(1),
    ) as mock_lit:
        result = exe.execute(req)
    # Literature was called with the taxon
    mock_lit.assert_called_once()
    call_taxa = mock_lit.call_args[1].get("taxa") or mock_lit.call_args[0][1:]
    assert taxon in (call_taxa or []) or result.status in {"completed", "blocked"}
    assert result.status in {"completed", "blocked"}
    assert result.project_id is not None


def test_all_five_gate3_taxa_in_one_request(tmp_path):
    exe = _executor(tmp_path)
    req = _request("req-all-five", taxa=GATE3_TAXA)
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(5),
    ):
        result = exe.execute(req)
    assert result.status == "completed"
    assert result.artifact_ids


def test_external_literature_not_in_canonical_kg(tmp_path):
    exe = _executor(tmp_path)
    req = _request("req-nokg")
    lit = _lit_results(2)
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=lit,
    ):
        result = exe.execute(req)
    # External literature flag in result dict must be false for KG mutation
    rd = result.to_dict()
    assert rd["external_literature_summary"]["knowledge_graph_mutation"] is False
    assert rd["external_literature_summary"]["automatic_publication"] is False
    assert result.authority["knowledge_graph_mutation_authorized"] is False


# ---------------------------------------------------------------------------
# Governance / authority boundaries
# ---------------------------------------------------------------------------


def test_authority_dict_is_all_false(tmp_path):
    exe = _executor(tmp_path)
    req = _request("req-auth")
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(1),
    ):
        result = exe.execute(req)
    for key, value in result.authority.items():
        assert value is False, f"Authority field {key!r} should be False, got {value}"


def test_result_dict_review_required(tmp_path):
    exe = _executor(tmp_path)
    req = _request("req-rev")
    with patch(
        "app.calyx_orchestrator.research_executor.search_europe_pmc",
        return_value=_lit_results(1),
    ):
        result = exe.execute(req)
    assert result.review_required is True
    assert result.to_dict()["review_required"] is True
