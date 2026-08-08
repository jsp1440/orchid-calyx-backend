from pathlib import Path

import pytest
from fastapi import HTTPException

from app.routers import scientific_analysis as analysis_router
from runtime.research_station import ResearchStationService
from runtime.scientific_analysis import ScientificAnalysisService
from runtime.scientific_export_bundle import ScientificAnalysisExportService


def _route_fixture(tmp_path: Path):
    owner = "owner@example.test"
    project_id = "export-route-project"
    research = ResearchStationService(workspace=tmp_path / "research")
    research.create_project(
        owner,
        {
            "project_id": project_id,
            "title": "Export route project",
            "objective": "Verify protected reproducibility export routes.",
            "state": "active",
            "created_at": "2026-08-08T18:50:00Z",
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
            "provenance": {"source": "export-route-fixture"},
            "dataset_ref": {"dataset_id": "export-route-dataset"},
        },
    )["analysis"]
    exports = ScientificAnalysisExportService(analysis=analysis)
    return exports, owner, project_id, executed["analysis_id"]


def test_export_routes_are_registered_as_protected_analysis_surfaces():
    route_methods = {
        (route.path, method)
        for route in analysis_router.router.routes
        for method in getattr(route, "methods", set())
    }

    assert (
        "/brain/mission-control/research/analysis/projects/{project_id}/results/{analysis_id}/exports",
        "POST",
    ) in route_methods
    assert (
        "/brain/mission-control/research/analysis/projects/{project_id}/exports/{export_id}",
        "GET",
    ) in route_methods


def test_protected_export_build_and_get_delegate_to_owner_scoped_service(tmp_path, monkeypatch):
    exports, owner, project_id, analysis_id = _route_fixture(tmp_path)
    monkeypatch.setattr(analysis_router, "_export_instance", exports)

    built = analysis_router.build_analysis_export(project_id, analysis_id, {"actor": owner})
    bundle = built["export"]
    fetched = analysis_router.get_analysis_export(project_id, bundle["export_id"], {"actor": owner})

    assert bundle == fetched
    assert bundle["raw_dataset_rows_included"] is False
    assert bundle["diagnostic_payload_included"] is False
    assert bundle["private_research_artifact"] is True
    assert bundle["export_is_not_publication"] is True
    assert bundle["scientific_publication_authorized"] is False


def test_export_routes_fail_closed_without_owner_scope(tmp_path, monkeypatch):
    exports, _owner, project_id, analysis_id = _route_fixture(tmp_path)
    monkeypatch.setattr(analysis_router, "_export_instance", exports)

    with pytest.raises(HTTPException) as caught:
        analysis_router.build_analysis_export(project_id, analysis_id, {})

    assert caught.value.status_code == 403


def test_export_route_translates_invalid_export_id_to_unprocessable_entity(tmp_path, monkeypatch):
    exports, owner, project_id, _analysis_id = _route_fixture(tmp_path)
    monkeypatch.setattr(analysis_router, "_export_instance", exports)

    with pytest.raises(HTTPException) as caught:
        analysis_router.get_analysis_export(project_id, "../private", {"actor": owner})

    assert caught.value.status_code == 422
    assert "ANALYSIS_EXPORT_ID_INVALID" in str(caught.value.detail)
