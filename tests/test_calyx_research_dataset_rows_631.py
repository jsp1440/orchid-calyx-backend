from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import research_dataset_rows as api
from app.security import verify_owner_or_api_key
from runtime.research_dataset_rows import ResearchDatasetRowStore, canonical_rows_sha256
from runtime.research_station import ResearchStationService

OWNER = "dataset-row-owner"
ROWS = [
    {"species": "Cattleya labiata", "elevation_m": 840, "flowers": 6},
    {"species": "Cattleya labiata", "elevation_m": 910, "flowers": 8},
    {"species": "Laelia purpurata", "elevation_m": 120, "flowers": 4},
]


def _stable(payload) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(payload) -> str:
    return hashlib.sha256(_stable(payload).encode()).hexdigest()


def _fixture(tmp_path: Path) -> tuple[ResearchStationService, ResearchDatasetRowStore, str, str]:
    research = ResearchStationService(tmp_path / "research")
    project_id = research.create_project(
        OWNER,
        {
            "project_id": "dataset-row-pilot",
            "title": "Dataset row pilot",
            "objective": "Exercise immutable registered row transport.",
            "state": "active",
            "created_at": "2026-08-08T04:20:00-07:00",
        },
    )["project"]["project_id"]
    checksum = _sha(ROWS)
    dataset_id = research.add_dataset(
        OWNER,
        project_id,
        {
            "dataset_id": "orchid-observations-v1",
            "title": "Orchid observations",
            "checksum_sha256": checksum,
            "schema_ref": "fixture/v1",
            "provenance": {"source": "test-fixture"},
        },
    )["dataset"]["dataset_id"]
    return research, ResearchDatasetRowStore(research), project_id, dataset_id


def test_canonical_checksum_matches_analysis_contract():
    assert canonical_rows_sha256(ROWS) == _sha(ROWS)


def test_registered_rows_are_private_immutable_and_replay_safe(tmp_path: Path):
    _research, store, project_id, dataset_id = _fixture(tmp_path)
    first = store.put(
        OWNER,
        project_id,
        dataset_id,
        ROWS,
        {"transport": "fixture", "registered_by": OWNER},
    )
    replay = store.put(
        OWNER,
        project_id,
        dataset_id,
        ROWS,
        {"transport": "fixture", "registered_by": OWNER},
    )
    record = store.get(OWNER, project_id, dataset_id)

    assert first["created"] is True
    assert replay["created"] is False
    assert record["rows"] == ROWS
    assert record["rows_sha256"] == _sha(ROWS)
    assert record["row_count"] == 3
    assert record["column_count"] == 3
    assert record["immutable"] is True
    assert record["private_by_default"] is True
    assert record["scientific_publication_authorized"] is False
    assert record["knowledge_graph_mutation_authorized"] is False


def test_checksum_mismatch_fails_closed(tmp_path: Path):
    _research, store, project_id, dataset_id = _fixture(tmp_path)
    altered = [*ROWS, {"species": "Extra", "elevation_m": 1, "flowers": 1}]
    try:
        store.put(OWNER, project_id, dataset_id, altered, {"source": "altered"})
    except ValueError as exc:
        assert "RESEARCH_DATASET_ROWS_CHECKSUM_MISMATCH" in str(exc)
    else:
        raise AssertionError("dataset row checksum mismatch must fail closed")


def test_conflicting_provenance_cannot_rewrite_immutable_rows(tmp_path: Path):
    _research, store, project_id, dataset_id = _fixture(tmp_path)
    store.put(OWNER, project_id, dataset_id, ROWS, {"source": "fixture-a"})
    try:
        store.put(OWNER, project_id, dataset_id, ROWS, {"source": "fixture-b"})
    except ValueError as exc:
        assert "RESEARCH_DATASET_ROWS_IMMUTABLE_CONFLICT" in str(exc)
    else:
        raise AssertionError("immutable row artifact provenance must not be rewritten")


def test_bounds_and_json_shape_fail_closed(tmp_path: Path):
    research, _store, project_id, dataset_id = _fixture(tmp_path)
    store = ResearchDatasetRowStore(research, maximum_rows=2)
    try:
        store.put(OWNER, project_id, dataset_id, ROWS, {"source": "fixture"})
    except ValueError as exc:
        assert "RESEARCH_DATASET_ROWS_LIMIT_EXCEEDED" in str(exc)
    else:
        raise AssertionError("row limit must be enforced")


def test_readiness_reports_missing_then_available(tmp_path: Path):
    _research, store, project_id, dataset_id = _fixture(tmp_path)
    before = store.readiness(OWNER, project_id, dataset_id)
    assert before["rows_available"] is False
    store.put(OWNER, project_id, dataset_id, ROWS, {"source": "fixture"})
    after = store.readiness(OWNER, project_id, dataset_id)
    assert after["rows_available"] is True
    assert after["rows_sha256"] == _sha(ROWS)


def test_owner_scoped_protected_api_put_and_get(tmp_path: Path, monkeypatch):
    research, store, project_id, dataset_id = _fixture(tmp_path)
    monkeypatch.setattr(api, "_store", lambda: store)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": OWNER,
        "auth_type": "test",
    }
    client = TestClient(app)

    written = client.put(
        f"/brain/mission-control/research/projects/{project_id}/datasets/{dataset_id}/rows",
        json={"rows": ROWS, "provenance": {"source": "api-fixture"}},
    )
    assert written.status_code == 200
    fetched = client.get(
        f"/brain/mission-control/research/projects/{project_id}/datasets/{dataset_id}/rows"
    )
    assert fetched.status_code == 200
    assert fetched.json()["rows"] == ROWS
    assert fetched.json()["dataset_checksum_sha256"] == canonical_rows_sha256(ROWS)

    wrong_owner = ResearchDatasetRowStore(research)
    try:
        wrong_owner.get("another-owner", project_id, dataset_id)
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("owner scope must isolate dataset rows")
