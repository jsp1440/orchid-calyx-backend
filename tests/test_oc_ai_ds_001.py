from __future__ import annotations

from pathlib import Path

import pytest

from app.university.ai_data_science import (
    MODULE_ID,
    PROGRAM_ID,
    AppliedAIDataScienceService,
)
from runtime.research_station import ResearchStationService


def _rows() -> list[dict]:
    return [
        {
            "occurrence_id": "GBIF:1",
            "scientific_name": "Cypripedium acaule",
            "taxon_id": "taxon-1",
            "decimal_latitude": 44.1,
            "decimal_longitude": -70.2,
            "locality": "restricted bog A",
            "country_code": "US",
            "state_province": "Maine",
            "year": 2020,
            "month": 6,
            "elevation_m": 0,
            "source": "GBIF",
            "license": "CC BY 4.0",
            "basis_of_record": "HUMAN_OBSERVATION",
        },
        {
            "occurrence_id": "GBIF:2",
            "scientific_name": "Cypripedium acaule",
            "taxon_id": "taxon-1",
            "lat": 44.2,
            "lon": -70.3,
            "site_name": "restricted bog B",
            "country_code": "US",
            "state_province": "Maine",
            "year": 2021,
            "month": 6,
            "elevation_m": 120,
            "source": "GBIF",
            "license": "CC BY 4.0",
            "basis_of_record": "PRESERVED_SPECIMEN",
        },
        {
            "occurrence_id": "INAT:3",
            "scientific_name": "Platanthera blephariglottis",
            "taxon_id": "taxon-2",
            "coordinates": [45.0, -79.0],
            "location_notes": "sensitive wetland",
            "country_code": "CA",
            "state_province": "Ontario",
            "year": 2022,
            "month": 7,
            "elevation_m": None,
            "source": "iNaturalist",
            "license": "CC BY-NC",
            "basis_of_record": "HUMAN_OBSERVATION",
        },
        {
            "occurrence_id": "INAT:4",
            "scientific_name": "Platanthera blephariglottis",
            "taxon_id": "taxon-2",
            "geometry": {"type": "Point", "coordinates": [-79.1, 45.1]},
            "country_code": "CA",
            "state_province": "Ontario",
            "year": 2023,
            "month": 7,
            "elevation_m": 350,
            "source": "iNaturalist",
            "license": "CC BY-NC",
            "basis_of_record": "HUMAN_OBSERVATION",
        },
    ]


def _service(tmp_path: Path) -> AppliedAIDataScienceService:
    research = ResearchStationService(workspace=tmp_path / "research")
    return AppliedAIDataScienceService(research)


def _prepare(service: AppliedAIDataScienceService) -> dict:
    return service.prepare(
        "learner@example.test",
        {
            "rows": _rows(),
            "provenance": {
                "source": "bounded-test-view",
                "dataset_id": "fixture-occurrences",
                "locality": "must never survive",
                "nested": {
                    "decimal_latitude": 44.1,
                    "license": "mixed-source fixture",
                },
            },
            "selection": {
                "taxa": ["Cypripedium acaule", "Platanthera blephariglottis"],
                "geometry": {"type": "Polygon", "coordinates": []},
                "country_code": ["US", "CA"],
            },
            "recorded_at": "2026-08-22T03:30:00Z",
        },
    )


def _assert_no_exact_locality(value) -> None:
    blocked = {
        "latitude",
        "longitude",
        "lat",
        "lon",
        "lng",
        "decimal_latitude",
        "decimal_longitude",
        "coordinates",
        "coordinate",
        "geometry",
        "geom",
        "geopoint",
        "locality",
        "exact_locality",
        "site",
        "site_name",
        "address",
        "landowner",
        "property_name",
        "location_notes",
    }
    if isinstance(value, dict):
        assert not (blocked & {str(key).casefold() for key in value})
        for nested in value.values():
            _assert_no_exact_locality(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_exact_locality(nested)


def test_module_contract_is_executable_but_non_authoritative(tmp_path):
    module = _service(tmp_path).module()
    assert module["program_id"] == PROGRAM_ID
    assert module["module_id"] == MODULE_ID
    assert module["progression"] == ["LEARN", "APPLY", "RESEARCH"]
    assert module["analysis_contract"]["method"] == "describe.v1"
    assert module["dataset_contract"]["exact_coordinates_in_educational_view"] is False
    assert module["dataset_contract"]["measured_zero_preserved"] is True
    assert module["calyx_tutor_contract"]["generated_explanation_is_evidence"] is False
    assert module["research_station_contract"]["scientific_publication_authorized"] is False
    assert module["research_station_contract"]["knowledge_graph_mutation_authorized"] is False
    assert module["research_station_contract"]["taxonomy_mutation_authorized"] is False


def test_dataset_view_masks_locality_and_preserves_zero_vs_missing(tmp_path):
    service = _service(tmp_path)
    view = service.build_dataset_view(
        _rows(),
        {
            "source": "test",
            "decimal_latitude": 44.1,
            "nested": {"locality": "secret", "license": "fixture"},
        },
        {
            "geometry": {"type": "Polygon", "coordinates": [[1, 2]]},
            "country_code": "US",
        },
    )

    _assert_no_exact_locality(view)
    assert view["row_count"] == 4
    assert view["exact_coordinates_in_view"] is False
    assert view["exact_locality_in_view"] is False
    assert view["quality"]["elevation"]["complete"] == 3
    assert view["quality"]["elevation"]["missing"] == 1
    assert view["quality"]["elevation"]["measured_zero_count"] == 1
    assert view["quality"]["elevation"]["zero_is_not_used_for_missing"] is True
    assert view["rows"][0]["elevation_m"] == 0
    assert view["rows"][2]["elevation_m"] is None
    assert view["rows"][0]["country_code"] == "US"
    assert view["rows"][2]["state_province"] == "Ontario"


def test_prepare_builds_checksum_bound_manifest_snapshot_and_plan(tmp_path):
    service = _service(tmp_path)
    prepared = _prepare(service)
    manifest = prepared["lab_manifest"]
    view = prepared["dataset_view"]

    assert prepared["created"] is True
    assert manifest["program_id"] == PROGRAM_ID
    assert manifest["module_id"] == MODULE_ID
    assert manifest["dataset"]["rows_sha256"] == view["rows_sha256"]
    assert manifest["private_snapshot"]["rows_sha256"] == view["rows_sha256"]
    assert manifest["analysis_plan"]["dataset"]["checksum_sha256"] == view["rows_sha256"]
    assert manifest["analysis_plan"]["method"] == "describe.v1"
    assert manifest["analysis_plan"]["parameters"]["columns"] == ["elevation_m", "year"]
    assert manifest["execution"]["arbitrary_code_execution"] is False
    assert manifest["generated_explanation_is_evidence"] is False
    assert manifest["scientific_publication_authorized"] is False
    assert manifest["knowledge_graph_mutation_authorized"] is False
    _assert_no_exact_locality(manifest)
    _assert_no_exact_locality(view)

    fetched = service.get_manifest(
        "learner@example.test", manifest["project_id"], manifest["lab_manifest_id"]
    )
    assert fetched["manifest_sha256"] == manifest["manifest_sha256"]


def test_execute_replays_deterministically_and_promotes_by_reference(tmp_path):
    service = _service(tmp_path)
    prepared = _prepare(service)
    manifest = prepared["lab_manifest"]
    result = service.execute(
        "learner@example.test",
        manifest["project_id"],
        manifest["lab_manifest_id"],
        "2026-08-22T03:31:00Z",
    )

    elevation = result["result_table"]["columns"]["elevation_m"]
    assert elevation["n"] == 3
    assert elevation["missing"] == 1
    assert elevation["min"] == 0
    assert elevation["max"] == 350
    assert result["replay_proof"]["verified"] is True
    assert result["replay_proof"]["second_execution_reused_analysis"] is True
    assert result["visualization_payload"]["series"]["elevation_m"]["complete"] == 3
    assert result["visualization_payload"]["series"]["elevation_m"]["missing"] == 1

    calyx = result["calyx_context"]
    assert calyx["is_evidence"] is False
    assert calyx["generated_explanation_is_evidence"] is False
    assert calyx["model_call_performed"] is False

    promotion = result["research_promotion_packet"]
    assert promotion["project_id"] == manifest["project_id"]
    assert promotion["handoff"] == "by_reference"
    assert promotion["dataset"]["dataset_id"] == manifest["dataset"]["dataset_id"]
    assert promotion["dataset"]["rows_sha256"] == manifest["dataset"]["rows_sha256"]
    assert promotion["lab_manifest"]["lab_manifest_id"] == manifest["lab_manifest_id"]
    assert promotion["analysis_plan"]["plan_id"] == manifest["analysis_plan"]["plan_id"]
    assert promotion["analysis_result"]["result_sha256"] == result["replay_proof"]["result_sha256"]
    assert promotion["scientific_publication_authorized"] is False
    assert promotion["candidate_knowledge_promotion_authorized"] is False
    assert promotion["knowledge_graph_mutation_authorized"] is False
    assert promotion["taxonomy_mutation_authorized"] is False

    assert result["assessment"]["graded_automatically"] is False
    assert len(result["assessment"]["prompts"]) == 4
    _assert_no_exact_locality(result)


def test_prepare_and_execute_are_idempotent_for_same_inputs(tmp_path):
    service = _service(tmp_path)
    first_prepare = _prepare(service)
    second_prepare = _prepare(service)
    assert first_prepare["lab_manifest"]["lab_manifest_id"] == second_prepare["lab_manifest"]["lab_manifest_id"]
    assert first_prepare["lab_manifest"]["manifest_sha256"] == second_prepare["lab_manifest"]["manifest_sha256"]
    assert second_prepare["created"] is False

    manifest = first_prepare["lab_manifest"]
    first = service.execute(
        "learner@example.test",
        manifest["project_id"],
        manifest["lab_manifest_id"],
        "2026-08-22T03:31:00Z",
    )
    second = service.execute(
        "learner@example.test",
        manifest["project_id"],
        manifest["lab_manifest_id"],
        "2026-08-22T03:31:00Z",
    )
    assert first["replay_proof"]["analysis_id"] == second["replay_proof"]["analysis_id"]
    assert first["replay_proof"]["result_sha256"] == second["replay_proof"]["result_sha256"]
    assert first["research_promotion_packet"]["promotion_sha256"] == second["research_promotion_packet"]["promotion_sha256"]


def test_requires_at_least_two_complete_elevation_values(tmp_path):
    rows = _rows()
    rows[1]["elevation_m"] = None
    rows[3]["elevation_m"] = None
    service = _service(tmp_path)
    with pytest.raises(ValueError, match="OC_AI_DS_REQUIRES_TWO_ELEVATION_VALUES"):
        service.build_dataset_view(rows, {"source": "test"})
