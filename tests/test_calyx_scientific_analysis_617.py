from __future__ import annotations

import math
from pathlib import Path

import pytest

from runtime.research_station import ResearchStationService
from runtime.scientific_analysis import ScientificAnalysisService


def _project(tmp_path: Path):
    research = ResearchStationService(workspace=tmp_path / "research")
    research.create_project(
        "owner@example.test",
        {
            "project_id": "dracula-climate",
            "title": "Dracula climate comparison",
            "objective": "Test a deterministic analysis foundation.",
            "state": "active",
            "created_at": "2026-08-08T07:20:00Z",
        },
    )
    return ScientificAnalysisService(research), "owner@example.test", "dracula-climate"


def _payload(method: str, parameters: dict):
    return {
        "method": method,
        "parameters": parameters,
        "rows": [
            {"elevation_m": 1000, "rainfall_mm": 1400, "flowering_index": 1.0},
            {"elevation_m": 1200, "rainfall_mm": 1600, "flowering_index": 2.0},
            {"elevation_m": 1400, "rainfall_mm": 1800, "flowering_index": 3.0},
            {"elevation_m": 1600, "rainfall_mm": None, "flowering_index": 4.0},
        ],
        "provenance": {
            "source": "deterministic-test-fixture",
            "taxon_scope": "Dracula fixture",
        },
        "dataset_ref": {"dataset_id": "fixture-dracula-climate"},
        "missing_policy": "complete_case",
    }


def test_capabilities_are_bounded_and_non_publication_authority():
    capabilities = ScientificAnalysisService.capabilities()
    assert set(capabilities["methods"]) == {"describe.v1", "pearson.v1", "ols.v1"}
    assert capabilities["arbitrary_code_execution"] is False
    assert capabilities["autonomous_scientific_publication"] is False
    assert capabilities["knowledge_graph_mutation_authorized"] is False


def test_descriptive_statistics_are_deterministic_and_replay_safe(tmp_path):
    service, owner, project_id = _project(tmp_path)
    payload = _payload("describe.v1", {"columns": ["elevation_m", "rainfall_mm"]})
    first = service.execute(owner, project_id, payload)
    second = service.execute(owner, project_id, payload)

    assert first["created"] is True
    assert second["created"] is False
    assert first["analysis"]["analysis_id"] == second["analysis"]["analysis_id"]
    assert first["analysis"]["result"]["columns"]["elevation_m"]["mean"] == 1300.0
    assert first["analysis"]["result"]["columns"]["rainfall_mm"]["n"] == 3
    assert first["analysis"]["result"]["columns"]["rainfall_mm"]["missing"] == 1
    assert first["analysis"]["interpretation_generated"] is False
    assert first["analysis"]["human_review_required_for_scientific_conclusion"] is True


def test_pearson_complete_case_accounting(tmp_path):
    service, owner, project_id = _project(tmp_path)
    result = service.execute(
        owner,
        project_id,
        _payload("pearson.v1", {"x": "elevation_m", "y": "rainfall_mm"}),
    )["analysis"]

    assert result["rows_received"] == 4
    assert result["rows_or_values_dropped_for_missingness"] == 1
    assert result["result"]["n"] == 3
    assert math.isclose(result["result"]["r"], 1.0)
    assert math.isclose(result["result"]["r_squared"], 1.0)


def test_ols_returns_explicit_computed_output_without_significance_claim(tmp_path):
    service, owner, project_id = _project(tmp_path)
    result = service.execute(
        owner,
        project_id,
        _payload("ols.v1", {"x": "elevation_m", "y": "flowering_index"}),
    )["analysis"]

    assert result["result"]["n"] == 4
    assert math.isclose(result["result"]["slope"], 0.005)
    assert math.isclose(result["result"]["intercept"], -4.0)
    assert math.isclose(result["result"]["r_squared"], 1.0)
    assert "p_value" not in result["result"]
    assert result["scientific_publication_authorized"] is False


def test_validation_fails_closed_for_unsupported_method_and_missing_provenance(tmp_path):
    service, owner, project_id = _project(tmp_path)
    payload = _payload("pearson.v1", {"x": "elevation_m", "y": "rainfall_mm"})
    payload["method"] = "auto-pick-best-model"
    with pytest.raises(ValueError, match="ANALYSIS_METHOD_UNSUPPORTED"):
        service.validate(owner, project_id, payload)

    payload = _payload("pearson.v1", {"x": "elevation_m", "y": "rainfall_mm"})
    payload["provenance"] = {}
    with pytest.raises(ValueError, match="ANALYSIS_PROVENANCE_REQUIRED"):
        service.validate(owner, project_id, payload)


def test_zero_variance_is_rejected_instead_of_fabricating_statistic(tmp_path):
    service, owner, project_id = _project(tmp_path)
    payload = _payload("pearson.v1", {"x": "elevation_m", "y": "rainfall_mm"})
    payload["rows"] = [
        {"elevation_m": 1, "rainfall_mm": 10},
        {"elevation_m": 1, "rainfall_mm": 12},
    ]
    with pytest.raises(ValueError, match="ANALYSIS_PEARSON_ZERO_VARIANCE"):
        service.execute(owner, project_id, payload)
