from __future__ import annotations

import math
from pathlib import Path

import pytest

from runtime.research_analysis_workflow import (
    ResearchAnalysisWorkflowService,
    canonical_rows_sha256,
)
from runtime.research_station import ResearchStationService
from runtime.scientific_analysis import ScientificAnalysisService
from runtime.scientific_diagnostics import ScientificDiagnosticsService


def _fixture(tmp_path: Path):
    owner = "owner@example.test"
    project_id = "dracula-diagnostics"
    rows = [
        {"elevation_m": 1000, "flowering_index": 1.0},
        {"elevation_m": 1200, "flowering_index": 2.1},
        {"elevation_m": 1400, "flowering_index": 2.9},
        {"elevation_m": 1600, "flowering_index": 4.2},
    ]
    provenance = {"source": "diagnostics-test-fixture"}
    research = ResearchStationService(workspace=tmp_path / "research")
    research.create_project(
        owner,
        {
            "project_id": project_id,
            "title": "Dracula diagnostic fixture",
            "objective": "Verify deterministic non-interpretive diagnostics.",
            "state": "active",
            "created_at": "2026-08-08T09:05:00Z",
        },
    )
    research.add_dataset(
        owner,
        project_id,
        {
            "dataset_id": "dataset-dracula-diagnostics",
            "title": "Diagnostic rows",
            "checksum_sha256": canonical_rows_sha256(rows),
            "schema_ref": "fixture/v1",
            "provenance": {"source": "diagnostics-test-fixture"},
        },
    )
    analysis = ScientificAnalysisService(research)
    workflow = ResearchAnalysisWorkflowService(research, analysis)
    plan = workflow.create_plan(
        owner,
        project_id,
        {
            "question": "Does flowering index change with elevation?",
            "rationale": "OLS diagnostic fixture.",
            "dataset_id": "dataset-dracula-diagnostics",
            "variables": [
                {"name": "elevation_m", "kind": "numeric", "unit": "m", "role": "predictor"},
                {"name": "flowering_index", "kind": "numeric", "unit": "1", "role": "outcome"},
            ],
            "method": "ols.v1",
            "parameters": {"x": "elevation_m", "y": "flowering_index"},
            "created_by": owner,
            "created_at": "2026-08-08T09:06:00Z",
        },
    )["plan"]
    executed = workflow.execute_plan(
        owner,
        project_id,
        plan["plan_id"],
        {
            "rows": rows,
            "provenance": provenance,
            "recorded_at": "2026-08-08T09:07:00Z",
            "recorded_by": owner,
        },
    )
    diagnostics = ScientificDiagnosticsService(workflow)
    return diagnostics, owner, project_id, rows, provenance, plan, executed["analysis"]


def test_ols_diagnostics_are_plot_ready_checksums_and_non_interpretive(tmp_path):
    diagnostics, owner, project_id, rows, provenance, plan, analysis = _fixture(tmp_path)
    built = diagnostics.build(
        owner,
        project_id,
        plan["plan_id"],
        analysis["analysis_id"],
        rows,
        provenance,
    )
    artifact = built["diagnostic"]

    assert built["created"] is True
    assert artifact["analysis_id"] == analysis["analysis_id"]
    assert artifact["input_sha256"] == analysis["input_sha256"]
    assert artifact["result_sha256"] == analysis["result_sha256"]
    assert artifact["diagnostics_sha256"]
    assert artifact["diagnostics_are_descriptive_not_inferential"] is True
    assert artifact["model_quality_judgment_generated"] is False
    assert artifact["scientific_interpretation_generated"] is False
    assert artifact["scientific_publication_authorized"] is False

    observed = artifact["diagnostics"]["observed_fitted"]["points"]
    residual = artifact["diagnostics"]["residual_vs_fitted"]["points"]
    assert len(observed) == len(rows) == len(residual)
    assert all({"row_index", "x", "observed", "fitted", "residual"} <= set(point) for point in observed)
    assert math.isclose(sum(point["residual"] for point in observed), 0.0, abs_tol=1e-12)


def test_diagnostic_replay_is_idempotent(tmp_path):
    diagnostics, owner, project_id, rows, provenance, plan, analysis = _fixture(tmp_path)
    first = diagnostics.build(owner, project_id, plan["plan_id"], analysis["analysis_id"], rows, provenance)
    second = diagnostics.build(owner, project_id, plan["plan_id"], analysis["analysis_id"], rows, provenance)
    assert first["created"] is True
    assert second["created"] is False
    assert first["diagnostic"] == second["diagnostic"]
    assert diagnostics.get(owner, project_id, analysis["analysis_id"]) == first["diagnostic"]


def test_diagnostics_require_exact_analysis_input_identity(tmp_path):
    diagnostics, owner, project_id, rows, _provenance, plan, analysis = _fixture(tmp_path)
    with pytest.raises(ValueError, match="DIAGNOSTIC_ANALYSIS_INPUT_MISMATCH"):
        diagnostics.build(
            owner,
            project_id,
            plan["plan_id"],
            analysis["analysis_id"],
            rows,
            {"source": "different-provenance"},
        )
