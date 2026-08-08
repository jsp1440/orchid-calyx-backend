from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.research_analysis_workflow import (
    ResearchAnalysisWorkflowService,
    canonical_rows_sha256,
)
from runtime.research_station import ResearchStationService
from runtime.scientific_analysis import ScientificAnalysisService
from runtime.scientific_diagnostics import ScientificDiagnosticsService
from runtime.scientific_export_bundle import ScientificAnalysisExportService
from runtime.scientific_result_artifacts import ScientificResultArtifactService


def _plan_bound_fixture(tmp_path: Path):
    owner = "owner@example.test"
    project_id = "export-project"
    rows = [
        {"x": 1.0, "y": 1.0},
        {"x": 2.0, "y": 2.1},
        {"x": 3.0, "y": 2.9},
        {"x": 4.0, "y": 4.2},
    ]
    provenance = {"source": "export-fixture"}
    research = ResearchStationService(workspace=tmp_path / "research")
    research.create_project(
        owner,
        {
            "project_id": project_id,
            "title": "Export project",
            "objective": "Verify private reproducibility exports.",
            "state": "active",
            "created_at": "2026-08-08T18:30:00Z",
        },
    )
    research.add_dataset(
        owner,
        project_id,
        {
            "dataset_id": "dataset-export",
            "title": "Export dataset",
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
            "rationale": "Export reproducibility fixture.",
            "dataset_id": "dataset-export",
            "variables": [
                {"name": "x", "kind": "numeric", "unit": "1", "role": "predictor"},
                {"name": "y", "kind": "numeric", "unit": "1", "role": "outcome"},
            ],
            "method": "ols.v1",
            "parameters": {"x": "x", "y": "y"},
            "created_by": owner,
            "created_at": "2026-08-08T18:31:00Z",
        },
    )["plan"]
    execution = workflow.execute_plan(
        owner,
        project_id,
        plan["plan_id"],
        {
            "rows": rows,
            "provenance": provenance,
            "recorded_at": "2026-08-08T18:32:00Z",
            "recorded_by": owner,
        },
    )
    executed = execution["analysis"]
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
    artifacts.build(owner, project_id, executed["analysis_id"])
    exports = ScientificAnalysisExportService(analysis, workflow, diagnostics, artifacts)
    return exports, analysis, owner, project_id, executed, rows


def test_full_export_bundle_preserves_identity_without_private_rows(tmp_path):
    exports, _analysis, owner, project_id, executed, source_rows = _plan_bound_fixture(tmp_path)
    built = exports.build(owner, project_id, executed["analysis_id"])
    bundle = built["export"]

    assert built["created"] is True
    assert bundle["analysis_id"] == executed["analysis_id"]
    assert bundle["analysis"]["input_sha256"] == executed["input_sha256"]
    assert bundle["analysis"]["result_sha256"] == executed["result_sha256"]
    assert bundle["analysis_plan"]["plan_id"] == bundle["analysis_receipt"]["plan_id"]
    assert bundle["analysis_receipt"]["analysis_id"] == executed["analysis_id"]
    assert bundle["result_artifact"]["result_table"]["rows"]
    assert bundle["diagnostic_identity"]["diagnostic_id"]
    assert bundle["diagnostic_identity"]["diagnostics_sha256"]
    assert "diagnostics" not in bundle["diagnostic_identity"]
    assert "canonical_input" not in bundle["analysis"]
    assert "rows" not in bundle["analysis"]
    assert bundle["raw_dataset_rows_included"] is False
    assert bundle["diagnostic_payload_included"] is False
    assert bundle["private_research_artifact"] is True
    assert bundle["export_is_not_publication"] is True
    assert bundle["scientific_publication_authorized"] is False
    assert bundle["knowledge_graph_mutation_authorized"] is False
    assert source_rows not in bundle.values()
    assert exports.get(owner, project_id, bundle["export_id"]) == bundle


def test_export_bundle_replay_is_content_addressed_and_idempotent(tmp_path):
    exports, _analysis, owner, project_id, executed, _rows = _plan_bound_fixture(tmp_path)
    first = exports.build(owner, project_id, executed["analysis_id"])
    second = exports.build(owner, project_id, executed["analysis_id"])

    assert first["created"] is True
    assert second["created"] is False
    assert first["export"] == second["export"]
    assert first["export"]["export_id"].endswith(first["export"]["export_sha256"][:24])


def test_direct_analysis_exports_without_plan_receipt_or_diagnostics(tmp_path):
    owner = "owner@example.test"
    project_id = "direct-export-project"
    research = ResearchStationService(workspace=tmp_path / "research")
    research.create_project(
        owner,
        {
            "project_id": project_id,
            "title": "Direct export",
            "objective": "Verify bounded direct-analysis export.",
            "state": "active",
            "created_at": "2026-08-08T18:33:00Z",
        },
    )
    analysis = ScientificAnalysisService(research)
    executed = analysis.execute(
        owner,
        project_id,
        {
            "method": "describe.v1",
            "parameters": {"columns": ["value"]},
            "rows": [{"value": 1.0}, {"value": 2.0}],
            "provenance": {"source": "direct-export-fixture"},
            "dataset_ref": {"dataset_id": "external-direct"},
        },
    )["analysis"]
    exports = ScientificAnalysisExportService(analysis=analysis)
    bundle = exports.build(owner, project_id, executed["analysis_id"])["export"]

    assert bundle["component_presence"] == {
        "analysis": True,
        "analysis_plan": False,
        "analysis_receipt": False,
        "result_artifact": False,
        "diagnostic_identity": False,
    }
    assert bundle["analysis_plan"] is None
    assert bundle["analysis_receipt"] is None
    assert bundle["result_artifact"] is None
    assert bundle["diagnostic_identity"] is None
    assert bundle["raw_dataset_rows_included"] is False


def test_export_bundle_fails_closed_on_receipt_identity_mismatch(tmp_path):
    exports, analysis, owner, project_id, executed, _rows = _plan_bound_fixture(tmp_path)
    root = analysis._project_root(owner, project_id)
    receipt_path = root / "analysis_receipts" / f"{executed['analysis_id']}.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["result_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ValueError, match="ANALYSIS_EXPORT_RECEIPT_IDENTITY_MISMATCH"):
        exports.build(owner, project_id, executed["analysis_id"])


def test_export_bundle_rejects_invalid_export_identifier(tmp_path):
    exports, _analysis, owner, project_id, _executed, _rows = _plan_bound_fixture(tmp_path)
    with pytest.raises(ValueError, match="ANALYSIS_EXPORT_ID_INVALID"):
        exports.get(owner, project_id, "../private")
