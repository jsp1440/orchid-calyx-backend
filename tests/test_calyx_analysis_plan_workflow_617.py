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


def _variables():
    return [
        {"name": "elevation_m", "kind": "numeric", "unit": "m", "role": "predictor"},
        {"name": "flowering_index", "kind": "numeric", "unit": "1", "role": "outcome"},
    ]


def _fixture(tmp_path: Path):
    owner = "owner@example.test"
    project_id = "dracula-analysis-plan"
    rows = [
        {"elevation_m": 1000, "flowering_index": 1.0},
        {"elevation_m": 1200, "flowering_index": 2.0},
        {"elevation_m": 1400, "flowering_index": 3.0},
        {"elevation_m": 1600, "flowering_index": 4.0},
    ]
    research = ResearchStationService(workspace=tmp_path / "research")
    research.create_project(
        owner,
        {
            "project_id": project_id,
            "title": "Dracula analysis plan",
            "objective": "Verify explicit plan and exact dataset binding.",
            "state": "active",
            "created_at": "2026-08-08T07:30:00Z",
        },
    )
    checksum = canonical_rows_sha256(rows)
    research.add_dataset(
        owner,
        project_id,
        {
            "dataset_id": "dataset-dracula-analysis",
            "title": "Dracula elevation and flowering fixture",
            "checksum_sha256": checksum,
            "schema_ref": "fixture/v1",
            "provenance": {"source": "deterministic-test-fixture"},
        },
    )
    analysis = ScientificAnalysisService(research)
    workflow = ResearchAnalysisWorkflowService(research, analysis)
    plan = workflow.create_plan(
        owner,
        project_id,
        {
            "question": "Does flowering index change linearly with elevation?",
            "rationale": "Use a pre-specified simple OLS model for the bounded fixture.",
            "dataset_id": "dataset-dracula-analysis",
            "variables": _variables(),
            "method": "ols.v1",
            "parameters": {"x": "elevation_m", "y": "flowering_index"},
            "created_by": owner,
            "created_at": "2026-08-08T07:31:00Z",
        },
    )["plan"]
    return workflow, research, owner, project_id, rows, plan


def test_plan_is_immutable_and_binds_registered_dataset(tmp_path):
    workflow, _research, owner, project_id, rows, plan = _fixture(tmp_path)
    validation = workflow.validate_plan_rows(
        owner,
        project_id,
        plan["plan_id"],
        rows,
        {"source": "analysis-workbench-test"},
    )
    assert validation["valid"] is True
    assert validation["dataset_id"] == "dataset-dracula-analysis"
    assert validation["dataset_checksum_sha256"] == canonical_rows_sha256(rows)
    assert validation["submitted_raw_rows_sha256"] == canonical_rows_sha256(rows)
    assert validation["pre_filter_analytical_rows_sha256"] == canonical_rows_sha256(rows)
    assert validation["analytical_rows_sha256"] == canonical_rows_sha256(rows)
    assert validation["row_filter_receipt"]["rows_excluded"] == 0
    assert plan["variables"][0]["unit"] == "m"
    assert plan["method_auto_selected"] is False
    assert plan["scientific_publication_authorized"] is False


def test_checksum_mismatch_fails_closed_before_transform(tmp_path):
    workflow, _research, owner, project_id, rows, plan = _fixture(tmp_path)
    changed = [dict(row) for row in rows]
    changed[0]["elevation_m"] = 999
    with pytest.raises(ValueError, match="ANALYSIS_DATASET_CHECKSUM_MISMATCH"):
        workflow.validate_plan_rows(
            owner,
            project_id,
            plan["plan_id"],
            changed,
            {"source": "analysis-workbench-test"},
        )


def test_numeric_variable_requires_unit(tmp_path):
    workflow, _research, owner, project_id, _rows, _plan = _fixture(tmp_path)
    variables = _variables()
    variables[0] = {"name": "elevation_m", "kind": "numeric", "unit": "", "role": "predictor"}
    with pytest.raises(ValueError, match="ANALYSIS_NUMERIC_VARIABLE_UNIT_REQUIRED"):
        workflow.create_plan(
            owner,
            project_id,
            {
                "question": "Does elevation matter?",
                "rationale": "Unit validation fixture.",
                "dataset_id": "dataset-dracula-analysis",
                "variables": variables,
                "method": "ols.v1",
                "parameters": {"x": "elevation_m", "y": "flowering_index"},
                "created_by": owner,
                "created_at": "2026-08-08T07:32:00Z",
            },
        )


def test_governed_zscore_creates_derived_variable_with_receipt(tmp_path):
    workflow, _research, owner, project_id, rows, _plan = _fixture(tmp_path)
    created = workflow.create_plan(
        owner,
        project_id,
        {
            "question": "Does standardized elevation predict flowering index?",
            "rationale": "Exercise the governed transformation engine.",
            "dataset_id": "dataset-dracula-analysis",
            "variables": _variables(),
            "method": "ols.v1",
            "parameters": {"x": "elevation_z", "y": "flowering_index"},
            "transformations": [
                {
                    "operation": "zscore",
                    "source": "elevation_m",
                    "target": "elevation_z",
                    "unit": "1",
                    "role": "predictor",
                }
            ],
            "created_by": owner,
            "created_at": "2026-08-08T07:32:00Z",
        },
    )["plan"]
    validation = workflow.validate_plan_rows(
        owner,
        project_id,
        created["plan_id"],
        rows,
        {"source": "analysis-workbench-test"},
    )
    assert validation["submitted_raw_rows_sha256"] == canonical_rows_sha256(rows)
    assert validation["pre_filter_analytical_rows_sha256"] != canonical_rows_sha256(rows)
    assert validation["analytical_rows_sha256"] == validation["pre_filter_analytical_rows_sha256"]
    receipt = validation["transformation_receipts"][0]
    assert receipt["operation"] == "zscore"
    assert receipt["complete_values"] == 4
    assert math.isclose(receipt["execution_context"]["mean"], 1300.0)
    assert receipt["output_sha256"]
    assert created["analytical_variables"][-1]["name"] == "elevation_z"
    assert created["analytical_variables"][-1]["unit"] == "1"


def test_transform_domain_errors_fail_closed(tmp_path):
    workflow, research, owner, project_id, _rows, _plan = _fixture(tmp_path)
    rows = [
        {"elevation_m": 1000, "flowering_index": 1.0},
        {"elevation_m": 1200, "flowering_index": 0.0},
    ]
    research.add_dataset(
        owner,
        project_id,
        {
            "dataset_id": "dataset-log-domain",
            "title": "Log-domain fixture",
            "checksum_sha256": canonical_rows_sha256(rows),
            "schema_ref": "fixture/v1",
            "provenance": {"source": "deterministic-test-fixture"},
        },
    )
    plan = workflow.create_plan(
        owner,
        project_id,
        {
            "question": "Log transform flowering index?",
            "rationale": "Domain failure fixture.",
            "dataset_id": "dataset-log-domain",
            "variables": _variables(),
            "method": "ols.v1",
            "parameters": {"x": "elevation_m", "y": "log_flowering"},
            "transformations": [
                {
                    "operation": "log10",
                    "source": "flowering_index",
                    "target": "log_flowering",
                    "unit": "log10(1)",
                }
            ],
            "created_by": owner,
            "created_at": "2026-08-08T07:32:30Z",
        },
    )["plan"]
    with pytest.raises(ValueError, match="ANALYSIS_TRANSFORMATION_LOG10_DOMAIN"):
        workflow.validate_plan_rows(
            owner,
            project_id,
            plan["plan_id"],
            rows,
            {"source": "analysis-workbench-test"},
        )


def test_legacy_free_text_exclusions_are_rejected(tmp_path):
    workflow, _research, owner, project_id, _rows, _plan = _fixture(tmp_path)
    with pytest.raises(
        ValueError,
        match="ANALYSIS_PLAN_LEGACY_EXCLUSIONS_FORBIDDEN_USE_ROW_FILTERS",
    ):
        workflow.create_plan(
            owner,
            project_id,
            {
                "question": "Exclude an observation?",
                "rationale": "Ensure free-text exclusions cannot be merely claimed.",
                "dataset_id": "dataset-dracula-analysis",
                "variables": _variables(),
                "method": "ols.v1",
                "parameters": {"x": "elevation_m", "y": "flowering_index"},
                "exclusions": ["row 1"],
                "created_by": owner,
                "created_at": "2026-08-08T07:32:45Z",
            },
        )


def test_governed_row_filter_preserves_counts_hashes_and_reason(tmp_path):
    workflow, _research, owner, project_id, rows, _plan = _fixture(tmp_path)
    plan = workflow.create_plan(
        owner,
        project_id,
        {
            "question": "Does flowering change above 1100 m?",
            "rationale": "Apply an explicitly pre-specified elevation inclusion threshold.",
            "dataset_id": "dataset-dracula-analysis",
            "variables": _variables(),
            "method": "ols.v1",
            "parameters": {"x": "elevation_m", "y": "flowering_index"},
            "row_filters": [
                {
                    "variable": "elevation_m",
                    "operator": "gte",
                    "value": 1100,
                    "reason_code": "BELOW_PREDEFINED_ELEVATION_SCOPE",
                }
            ],
            "created_by": owner,
            "created_at": "2026-08-08T07:34:00Z",
        },
    )["plan"]
    validation = workflow.validate_plan_rows(
        owner,
        project_id,
        plan["plan_id"],
        rows,
        {"source": "analysis-workbench-test"},
    )
    receipt = validation["row_filter_receipt"]
    assert receipt["rows_before"] == 4
    assert receipt["rows_after"] == 3
    assert receipt["rows_excluded"] == 1
    assert receipt["excluded_rows"][0]["source_position"] == 1
    assert receipt["excluded_rows"][0]["row_identity"].startswith("row-1-")
    assert receipt["excluded_rows"][0]["reason_codes"] == [
        "BELOW_PREDEFINED_ELEVATION_SCOPE"
    ]
    assert receipt["receipt_sha256"]
    assert validation["submitted_raw_rows_sha256"] == canonical_rows_sha256(rows)
    assert validation["pre_filter_analytical_rows_sha256"] == canonical_rows_sha256(rows)
    assert validation["analytical_rows_sha256"] != canonical_rows_sha256(rows)
    assert validation["analysis_validation"]["row_count"] == 3


def test_filter_can_reference_declared_derived_variable(tmp_path):
    workflow, _research, owner, project_id, rows, _plan = _fixture(tmp_path)
    plan = workflow.create_plan(
        owner,
        project_id,
        {
            "question": "Analyze observations at or above the mean standardized elevation?",
            "rationale": "Verify filters run after declared transformations.",
            "dataset_id": "dataset-dracula-analysis",
            "variables": _variables(),
            "method": "ols.v1",
            "parameters": {"x": "elevation_z", "y": "flowering_index"},
            "transformations": [
                {
                    "operation": "zscore",
                    "source": "elevation_m",
                    "target": "elevation_z",
                    "unit": "1",
                }
            ],
            "row_filters": [
                {
                    "variable": "elevation_z",
                    "operator": "gte",
                    "value": 0,
                    "reason_code": "BELOW_STANDARDIZED_MEAN_SCOPE",
                }
            ],
            "created_by": owner,
            "created_at": "2026-08-08T07:34:10Z",
        },
    )["plan"]
    validation = workflow.validate_plan_rows(
        owner,
        project_id,
        plan["plan_id"],
        rows,
        {"source": "analysis-workbench-test"},
    )
    assert validation["row_filter_receipt"]["rows_after"] == 2
    assert validation["analysis_validation"]["row_count"] == 2
    assert validation["pre_filter_analytical_rows_sha256"] != validation["analytical_rows_sha256"]


def test_filter_removing_all_rows_fails_closed(tmp_path):
    workflow, _research, owner, project_id, rows, _plan = _fixture(tmp_path)
    plan = workflow.create_plan(
        owner,
        project_id,
        {
            "question": "Impossible bounded scope fixture",
            "rationale": "Verify zero-row filters fail closed.",
            "dataset_id": "dataset-dracula-analysis",
            "variables": _variables(),
            "method": "ols.v1",
            "parameters": {"x": "elevation_m", "y": "flowering_index"},
            "row_filters": [
                {
                    "variable": "elevation_m",
                    "operator": "gt",
                    "value": 9999,
                    "reason_code": "OUTSIDE_SCOPE",
                }
            ],
            "created_by": owner,
            "created_at": "2026-08-08T07:34:20Z",
        },
    )["plan"]
    with pytest.raises(ValueError, match="ANALYSIS_ROW_FILTER_REMOVED_ALL_ROWS"):
        workflow.validate_plan_rows(
            owner,
            project_id,
            plan["plan_id"],
            rows,
            {"source": "analysis-workbench-test"},
        )


def test_execute_plan_writes_one_replay_safe_notebook_receipt(tmp_path):
    workflow, research, owner, project_id, rows, plan = _fixture(tmp_path)
    payload = {
        "rows": rows,
        "provenance": {"source": "analysis-workbench-test"},
        "recorded_at": "2026-08-08T07:33:00Z",
        "recorded_by": owner,
    }
    first = workflow.execute_plan(owner, project_id, plan["plan_id"], payload)
    second = workflow.execute_plan(owner, project_id, plan["plan_id"], payload)

    assert first["analysis_created"] is True
    assert second["analysis_created"] is False
    assert first["analysis"]["analysis_id"] == second["analysis"]["analysis_id"]
    assert first["receipt"]["receipt_sha256"] == second["receipt"]["receipt_sha256"]
    assert first["receipt"]["raw_dataset_checksum_sha256"] == canonical_rows_sha256(rows)
    assert first["receipt"]["row_filter_receipt"]["rows_excluded"] == 0
    assert first["notebook"]["created"] is True
    assert second["notebook"]["created"] is False
    manifest = research.manifest(owner, project_id)
    analysis_receipts = [
        revision
        for revision in manifest["notebook_revisions"]
        if revision["entry_id"].startswith("analysis-analysis-")
    ]
    assert len(analysis_receipts) == 1
    assert first["analysis"]["interpretation_generated"] is False
    assert first["receipt"]["scientific_publication_authorized"] is False
