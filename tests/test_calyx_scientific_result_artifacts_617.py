from __future__ import annotations

from pathlib import Path

from runtime.research_analysis_workflow import (
    ResearchAnalysisWorkflowService,
    canonical_rows_sha256,
)
from runtime.research_station import ResearchStationService
from runtime.scientific_analysis import ScientificAnalysisService
from runtime.scientific_diagnostics import ScientificDiagnosticsService
from runtime.scientific_result_artifacts import ScientificResultArtifactService


def _fixture(tmp_path: Path):
    owner = "owner@example.test"
    project_id = "result-artifact-project"
    rows = [
        {"x": 1.0, "y": 1.0},
        {"x": 2.0, "y": 2.2},
        {"x": 3.0, "y": 2.8},
        {"x": 4.0, "y": 4.1},
    ]
    provenance = {"source": "result-artifact-fixture"}
    research = ResearchStationService(workspace=tmp_path / "research")
    research.create_project(
        owner,
        {
            "project_id": project_id,
            "title": "Result artifact project",
            "objective": "Verify immutable result table and figure specs.",
            "state": "active",
            "created_at": "2026-08-08T09:20:00Z",
        },
    )
    research.add_dataset(
        owner,
        project_id,
        {
            "dataset_id": "dataset-result-artifact",
            "title": "Result artifact dataset",
            "checksum_sha256": canonical_rows_sha256(rows),
            "schema_ref": "fixture/v1",
            "provenance": provenance,
        },
    )
    analysis = ScientificAnalysisService(research)
    workflow = ResearchAnalysisWorkflowService(research, analysis)
    plan = workflow.create_plan(
        owner,
        project_id,
        {
            "question": "Does y vary linearly with x?",
            "rationale": "OLS artifact fixture.",
            "dataset_id": "dataset-result-artifact",
            "variables": [
                {"name": "x", "kind": "numeric", "unit": "1", "role": "predictor"},
                {"name": "y", "kind": "numeric", "unit": "1", "role": "outcome"},
            ],
            "method": "ols.v1",
            "parameters": {"x": "x", "y": "y"},
            "created_by": owner,
            "created_at": "2026-08-08T09:21:00Z",
        },
    )["plan"]
    executed = workflow.execute_plan(
        owner,
        project_id,
        plan["plan_id"],
        {
            "rows": rows,
            "provenance": provenance,
            "recorded_at": "2026-08-08T09:22:00Z",
            "recorded_by": owner,
        },
    )["analysis"]
    diagnostics = ScientificDiagnosticsService(workflow)
    diagnostics.build(
        owner,
        project_id,
        plan["plan_id"],
        executed["analysis_id"],
        rows,
        provenance,
    )
    artifacts = ScientificResultArtifactService(analysis, diagnostics)
    return artifacts, owner, project_id, executed


def test_result_artifact_contains_table_and_diagnostic_backed_figures(tmp_path):
    artifacts, owner, project_id, analysis = _fixture(tmp_path)
    built = artifacts.build(owner, project_id, analysis["analysis_id"])
    artifact = built["artifact"]

    assert built["created"] is True
    assert artifact["analysis_id"] == analysis["analysis_id"]
    assert artifact["result_sha256"] == analysis["result_sha256"]
    assert artifact["diagnostic_id"]
    assert artifact["diagnostics_sha256"]
    assert artifact["result_table"]["columns"] == [
        "n",
        "intercept",
        "slope",
        "r_squared",
        "residual_standard_error",
    ]
    assert len(artifact["result_table"]["rows"]) == 1
    assert [spec["figure_kind"] for spec in artifact["figure_specs"]] == [
        "observed_vs_fitted",
        "residual_vs_fitted",
    ]
    assert all(spec["interpretation_generated"] is False for spec in artifact["figure_specs"])
    assert artifact["figure_specs_are_rendering_instructions_not_interpretation"] is True
    assert artifact["scientific_interpretation_generated"] is False
    assert artifact["scientific_publication_authorized"] is False


def test_result_artifact_replay_is_idempotent(tmp_path):
    artifacts, owner, project_id, analysis = _fixture(tmp_path)
    first = artifacts.build(owner, project_id, analysis["analysis_id"])
    second = artifacts.build(owner, project_id, analysis["analysis_id"])
    assert first["created"] is True
    assert second["created"] is False
    assert first["artifact"] == second["artifact"]
    assert artifacts.get(owner, project_id, analysis["analysis_id"]) == first["artifact"]
