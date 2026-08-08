from pathlib import Path

import pytest

from runtime.research_station import ResearchStationService
from runtime.scientific_analysis import ScientificAnalysisService
from runtime.scientific_analysis_history import ScientificAnalysisHistoryService


def _services(tmp_path: Path):
    research = ResearchStationService(workspace=tmp_path / "research")
    owner = "owner@example.test"
    project_id = "history-project"
    research.create_project(
        owner,
        {
            "project_id": project_id,
            "title": "Analysis discovery fixture",
            "objective": "Discover immutable analyses without ranking them.",
            "state": "active",
            "created_at": "2026-08-08T18:20:00Z",
        },
    )
    analysis = ScientificAnalysisService(research)
    return analysis, ScientificAnalysisHistoryService(analysis), owner, project_id


def _payload(method: str, parameters: dict):
    return {
        "method": method,
        "parameters": parameters,
        "rows": [
            {"elevation_m": 1000, "flowering_index": 1.0},
            {"elevation_m": 1200, "flowering_index": 2.0},
            {"elevation_m": 1400, "flowering_index": 3.0},
        ],
        "provenance": {"source": "analysis-history-test"},
        "dataset_ref": {"dataset_id": "history-dataset"},
        "missing_policy": "complete_case",
    }


def test_analysis_history_lists_lightweight_immutable_records_without_ranking(tmp_path):
    analysis, history, owner, project_id = _services(tmp_path)
    first = analysis.execute(
        owner,
        project_id,
        _payload("describe.v1", {"columns": ["elevation_m"]}),
    )["analysis"]
    second = analysis.execute(
        owner,
        project_id,
        _payload("pearson.v1", {"x": "elevation_m", "y": "flowering_index"}),
    )["analysis"]

    result = history.list(owner, project_id)

    assert result["total"] == 2
    assert [item["analysis_id"] for item in result["items"]] == sorted(
        [first["analysis_id"], second["analysis_id"]]
    )
    assert result["ordering"] == "analysis_id_ascending_not_chronological"
    assert result["chronology_inferred"] is False
    assert result["results_included"] is False
    assert result["preferred_analysis"] is None
    assert result["scientific_superiority_determined"] is False
    assert result["mutation_authorized"] is False
    assert all("result" not in item for item in result["items"])
    assert all(item["scientific_publication_authorized"] is False for item in result["items"])


def test_analysis_history_paginates_deterministically(tmp_path):
    analysis, history, owner, project_id = _services(tmp_path)
    analysis.execute(
        owner,
        project_id,
        _payload("describe.v1", {"columns": ["elevation_m"]}),
    )
    analysis.execute(
        owner,
        project_id,
        _payload("pearson.v1", {"x": "elevation_m", "y": "flowering_index"}),
    )

    first_page = history.list(owner, project_id, limit=1, offset=0)
    second_page = history.list(owner, project_id, limit=1, offset=1)

    assert first_page["total"] == 2
    assert len(first_page["items"]) == 1
    assert len(second_page["items"]) == 1
    assert first_page["items"][0]["analysis_id"] != second_page["items"][0]["analysis_id"]


@pytest.mark.parametrize(
    ("limit", "offset"),
    [(0, 0), (201, 0), (1, -1), (True, 0)],
)
def test_analysis_history_rejects_invalid_pagination(tmp_path, limit, offset):
    _analysis, history, owner, project_id = _services(tmp_path)
    with pytest.raises(ValueError, match="ANALYSIS_HISTORY_PAGINATION_INVALID"):
        history.list(owner, project_id, limit=limit, offset=offset)


def test_analysis_history_enforces_project_scope(tmp_path):
    analysis, history, owner, project_id = _services(tmp_path)
    analysis.execute(
        owner,
        project_id,
        _payload("describe.v1", {"columns": ["elevation_m"]}),
    )

    with pytest.raises(FileNotFoundError):
        history.list(owner, "missing-project")
