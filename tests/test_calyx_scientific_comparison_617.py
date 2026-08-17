from __future__ import annotations

from pathlib import Path

from runtime.research_station import ResearchStationService
from runtime.scientific_analysis import ScientificAnalysisService
from runtime.scientific_comparison import ScientificComparisonService


def _service(tmp_path: Path):
    owner = "owner@example.test"
    project_id = "comparison-project"
    research = ResearchStationService(workspace=tmp_path / "research")
    research.create_project(
        owner,
        {
            "project_id": project_id,
            "title": "Comparison project",
            "objective": "Verify descriptive analysis comparison.",
            "state": "active",
            "created_at": "2026-08-08T09:12:00Z",
        },
    )
    analysis = ScientificAnalysisService(research)
    return ScientificComparisonService(analysis), analysis, owner, project_id


def _run(analysis, owner, project_id, rows, dataset_id):
    return analysis.execute(
        owner,
        project_id,
        {
            "method": "ols.v1",
            "parameters": {"x": "x", "y": "y"},
            "rows": rows,
            "provenance": {"source": dataset_id},
            "dataset_ref": {
                "dataset_id": dataset_id,
                "raw_checksum_sha256": f"{dataset_id:0<64}"[:64],
                "analytical_rows_sha256": f"analytical-{dataset_id:0<64}"[:64],
            },
            "missing_policy": "complete_case",
        },
    )["analysis"]


def test_same_method_comparison_reports_deltas_without_winner(tmp_path):
    comparison, analysis, owner, project_id = _service(tmp_path)
    a = _run(
        analysis,
        owner,
        project_id,
        [{"x": 1, "y": 1}, {"x": 2, "y": 2}, {"x": 3, "y": 3}],
        "dataset-a",
    )
    b = _run(
        analysis,
        owner,
        project_id,
        [{"x": 1, "y": 1}, {"x": 2, "y": 2.2}, {"x": 3, "y": 3.4}],
        "dataset-b",
    )
    result = comparison.compare(owner, project_id, a["analysis_id"], b["analysis_id"])
    artifact = result["comparison"]

    assert result["created"] is True
    assert artifact["same_method"] is True
    assert artifact["same_method_version"] is True
    assert artifact["compatibility"] == "same_method_different_or_unbound_dataset"
    assert "slope" in artifact["numeric_result_deltas"]
    assert artifact["preferred_analysis"] is None
    assert artifact["scientific_superiority_determined"] is False
    assert artifact["comparison_is_descriptive_not_model_selection"] is True
    assert artifact["scientific_interpretation_generated"] is False


def test_identical_run_comparison_is_idempotent(tmp_path):
    comparison, analysis, owner, project_id = _service(tmp_path)
    a = _run(
        analysis,
        owner,
        project_id,
        [{"x": 1, "y": 1}, {"x": 2, "y": 2}, {"x": 3, "y": 3}],
        "dataset-a",
    )
    first = comparison.compare(owner, project_id, a["analysis_id"], a["analysis_id"])
    second = comparison.compare(owner, project_id, a["analysis_id"], a["analysis_id"])
    assert first["comparison"]["compatibility"] == "identical_run"
    assert first["comparison"]["identical_input"] is True
    assert first["comparison"]["identical_result"] is True
    assert first["created"] is True
    assert second["created"] is False
    assert comparison.get(owner, project_id, first["comparison"]["comparison_id"]) == first["comparison"]
