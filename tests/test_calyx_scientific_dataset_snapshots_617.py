from __future__ import annotations

from pathlib import Path

import pytest

from runtime.research_analysis_workflow import (
    ResearchAnalysisWorkflowService,
    canonical_rows_sha256,
)
from runtime.research_station import ResearchStationService
from runtime.scientific_analysis import ScientificAnalysisService
from runtime.scientific_dataset_snapshots import ScientificDatasetSnapshotService


def _fixture(tmp_path: Path):
    owner = "owner@example.test"
    project_id = "snapshot-project"
    dataset_id = "dataset-snapshot-fixture"
    rows = [
        {"elevation_m": 1000, "flowering_index": 1.0},
        {"elevation_m": 1200, "flowering_index": 2.0},
        {"elevation_m": 1400, "flowering_index": 3.0},
    ]
    research = ResearchStationService(workspace=tmp_path / "research")
    research.create_project(
        owner,
        {
            "project_id": project_id,
            "title": "Snapshot project",
            "objective": "Exercise exact-row dataset snapshots.",
            "state": "active",
            "created_at": "2026-08-08T13:10:00Z",
        },
    )
    research.add_dataset(
        owner,
        project_id,
        {
            "dataset_id": dataset_id,
            "title": "Snapshot fixture",
            "checksum_sha256": canonical_rows_sha256(rows),
            "schema_ref": "fixture/v1",
            "provenance": {"source": "deterministic-test-fixture"},
        },
    )
    analysis = ScientificAnalysisService(research)
    workflow = ResearchAnalysisWorkflowService(research, analysis)
    snapshots = ScientificDatasetSnapshotService(workflow)
    return snapshots, owner, project_id, dataset_id, rows


def _payload(rows):
    return {
        "rows": rows,
        "provenance": {"source": "analysis-workbench-test"},
        "recorded_by": "owner@example.test",
        "recorded_at": "2026-08-08T13:11:00Z",
    }


def test_snapshot_requires_exact_registered_checksum_and_replays(tmp_path):
    snapshots, owner, project_id, dataset_id, rows = _fixture(tmp_path)
    first = snapshots.put(owner, project_id, dataset_id, _payload(rows))
    second = snapshots.put(owner, project_id, dataset_id, _payload(rows))

    assert first["created"] is True
    assert second["created"] is False
    assert first["snapshot"]["rows_sha256"] == canonical_rows_sha256(rows)
    assert first["snapshot"]["registered_checksum_sha256"] == canonical_rows_sha256(rows)
    assert first["snapshot"]["row_count"] == 3
    assert first["snapshot"]["columns"] == ["elevation_m", "flowering_index"]
    assert first["snapshot"]["scientific_publication_authorized"] is False


def test_snapshot_checksum_mismatch_fails_closed(tmp_path):
    snapshots, owner, project_id, dataset_id, rows = _fixture(tmp_path)
    changed = [dict(row) for row in rows]
    changed[0]["elevation_m"] = 999
    with pytest.raises(ValueError, match="ANALYSIS_DATASET_SNAPSHOT_CHECKSUM_MISMATCH"):
        snapshots.put(owner, project_id, dataset_id, _payload(changed))


def test_snapshot_list_omits_rows_but_explicit_get_returns_them(tmp_path):
    snapshots, owner, project_id, dataset_id, rows = _fixture(tmp_path)
    snapshots.put(owner, project_id, dataset_id, _payload(rows))

    listing = snapshots.list(owner, project_id)
    assert listing["count"] == 1
    assert "rows" not in listing["items"][0]
    assert listing["rows_are_returned_only_by_explicit_snapshot_get"] is True

    loaded = snapshots.get(owner, project_id, dataset_id)
    assert loaded["rows"] == rows
    assert loaded["private"] is True
    assert loaded["knowledge_graph_mutation_authorized"] is False


def test_snapshot_missing_registration_fails_closed(tmp_path):
    snapshots, owner, project_id, _dataset_id, rows = _fixture(tmp_path)
    with pytest.raises(FileNotFoundError):
        snapshots.put(owner, project_id, "dataset-not-registered", _payload(rows))


def test_snapshot_readiness_preserves_non_authority(tmp_path):
    snapshots, owner, project_id, dataset_id, rows = _fixture(tmp_path)
    snapshots.put(owner, project_id, dataset_id, _payload(rows))
    readiness = snapshots.readiness(owner, project_id)
    assert readiness["snapshot_count"] == 1
    assert readiness["registered_dataset_checksum_required"] is True
    assert readiness["private_snapshot_storage"] is True
    assert readiness["arbitrary_code_execution"] is False
    assert readiness["scientific_publication_authorized"] is False
    assert readiness["knowledge_graph_mutation_authorized"] is False
