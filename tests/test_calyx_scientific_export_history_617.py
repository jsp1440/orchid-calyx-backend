from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.research_station import ResearchStationService
from runtime.scientific_analysis import ScientificAnalysisService
from runtime.scientific_export_bundle import ScientificAnalysisExportService
from runtime.scientific_export_history import ScientificAnalysisExportHistoryService


def _fixture(tmp_path: Path):
    owner = "owner@example.test"
    project_id = "export-history-project"
    research = ResearchStationService(workspace=tmp_path / "research")
    research.create_project(
        owner,
        {
            "project_id": project_id,
            "title": "Export history",
            "objective": "Discover private export identities without bundle payloads.",
            "state": "active",
            "created_at": "2026-08-08T19:50:00Z",
        },
    )
    analysis = ScientificAnalysisService(research)
    exports = ScientificAnalysisExportService(analysis=analysis)
    built = []
    for index in range(3):
        executed = analysis.execute(
            owner,
            project_id,
            {
                "method": "describe.v1",
                "parameters": {"columns": ["value"]},
                "rows": [{"value": float(index + 1)}, {"value": float(index + 2)}],
                "provenance": {"source": f"history-fixture-{index}"},
                "dataset_ref": {"dataset_id": f"history-dataset-{index}"},
            },
        )["analysis"]
        built.append(exports.build(owner, project_id, executed["analysis_id"])["export"])
    history = ScientificAnalysisExportHistoryService(exports)
    return history, exports, owner, project_id, built


def test_private_export_history_lists_integrity_verified_metadata_only(tmp_path):
    history, _exports, owner, project_id, built = _fixture(tmp_path)

    listed = history.list(owner, project_id)

    assert listed["schema_version"] == "calyx-scientific-analysis-export-history/v1"
    assert listed["project_id"] == project_id
    assert listed["total"] == 3
    assert listed["ordering"] == "export_id_ascending_not_chronological"
    assert listed["chronology_inferred"] is False
    assert listed["bundle_payloads_included"] is False
    assert listed["raw_dataset_rows_included"] is False
    assert listed["diagnostic_payload_included"] is False
    assert listed["public_sharing_authorized"] is False
    assert listed["scientific_publication_authorized"] is False
    assert listed["knowledge_graph_mutation_authorized"] is False
    assert [item["export_id"] for item in listed["items"]] == sorted(
        bundle["export_id"] for bundle in built
    )
    for item in listed["items"]:
        assert set(item) == {
            "export_id",
            "export_sha256",
            "analysis_id",
            "profile",
            "component_presence",
            "numerical_environment_present",
            "raw_dataset_rows_included",
            "diagnostic_payload_included",
            "private_research_artifact",
            "export_is_not_publication",
            "scientific_publication_authorized",
            "knowledge_graph_mutation_authorized",
            "integrity_verified",
            "integrity_verification_is_not_publication_authority",
        }
        assert item["integrity_verified"] is True
        assert item["private_research_artifact"] is True
        assert item["export_is_not_publication"] is True
        assert item["scientific_publication_authorized"] is False
        assert "analysis" not in item
        assert "analysis_plan" not in item
        assert "result_artifact" not in item
        assert "diagnostic_identity" not in item


def test_private_export_history_filters_by_analysis_id_and_paginates_deterministically(tmp_path):
    history, _exports, owner, project_id, built = _fixture(tmp_path)
    target = built[1]

    filtered = history.list(owner, project_id, analysis_id=target["analysis_id"])
    page = history.list(owner, project_id, limit=1, offset=1)

    assert filtered["analysis_id_filter"] == target["analysis_id"]
    assert filtered["total"] == 1
    assert filtered["items"][0]["export_id"] == target["export_id"]
    expected = sorted(bundle["export_id"] for bundle in built)[1]
    assert page["items"][0]["export_id"] == expected
    assert page["limit"] == 1
    assert page["offset"] == 1


def test_private_export_history_rejects_invalid_filters_and_pagination(tmp_path):
    history, _exports, owner, project_id, _built = _fixture(tmp_path)

    with pytest.raises(ValueError, match="ANALYSIS_EXPORT_HISTORY_ANALYSIS_ID_INVALID"):
        history.list(owner, project_id, analysis_id="../analysis")
    with pytest.raises(TypeError, match="ANALYSIS_EXPORT_HISTORY_PAGINATION_INVALID"):
        history.list(owner, project_id, limit=True)
    with pytest.raises(ValueError, match="ANALYSIS_EXPORT_HISTORY_PAGINATION_INVALID"):
        history.list(owner, project_id, limit=0)
    with pytest.raises(ValueError, match="ANALYSIS_EXPORT_HISTORY_PAGINATION_INVALID"):
        history.list(owner, project_id, limit=201)


def test_private_export_history_fails_closed_if_persisted_export_is_tampered(tmp_path):
    history, exports, owner, project_id, built = _fixture(tmp_path)
    target = built[0]
    path = exports._root(owner, project_id) / "analysis_exports" / f"{target['export_id']}.json"
    persisted = json.loads(path.read_text(encoding="utf-8"))
    persisted["public_sharing_authorized"] = True
    path.write_text(json.dumps(persisted), encoding="utf-8")

    with pytest.raises(ValueError, match="ANALYSIS_EXPORT_INTEGRITY_MISMATCH"):
        history.list(owner, project_id)
