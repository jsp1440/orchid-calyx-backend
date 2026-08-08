from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import oasis_operational as api
from app.security import verify_owner_or_api_key
from runtime.conservatory_operational import ConservatoryService
from runtime.oasis_operational import OasisService

OWNER = "owner-a"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _plant(conservatory: ConservatoryService) -> str:
    result = conservatory.intake(
        OWNER,
        {
            "import_id": "oasis-fixture-import",
            "collection": {"collection_id": "orchids", "title": "Private Orchids"},
            "accession": {
                "accession_number": "OASIS-001",
                "acquired_at": "2026-08-07T10:00:00-07:00",
                "source": "fixture nursery",
            },
            "plant": {
                "display_name": "Cattleya labiata",
                "identity_state": "unresolved",
                "tag_text": "Cattleya labiata",
            },
            "location": {
                "location_id": "greenhouse-a",
                "label": "Greenhouse A",
                "privacy": "private",
            },
            "media": [
                {
                    "media_id": "oasis-plant-photo",
                    "role": "plant",
                    "sha256": _sha("oasis-plant-photo"),
                    "source_uri": "upload://oasis/plant.jpg",
                    "license": "private-owner-media",
                    "attribution": "Owner",
                }
            ],
        },
    )
    return result["plant_id"]


def _configured(tmp_path: Path) -> tuple[ConservatoryService, OasisService, str]:
    conservatory = ConservatoryService(tmp_path / "conservatory")
    plant_id = _plant(conservatory)
    oasis = OasisService(tmp_path / "oasis", conservatory=conservatory)
    oasis.configure_space(
        OWNER,
        {
            "space_id": "gh-a",
            "label": "Greenhouse A",
            "conservatory_location_id": "greenhouse-a",
        },
    )
    sensors = [
        ("temp", "temperature_c", "C"),
        ("rh", "humidity_pct", "%"),
        ("light", "light_ppfd", "umol/m2/s"),
        ("moisture", "substrate_moisture_pct", "%"),
        ("vent", "ventilation_state", "state"),
    ]
    for sensor_id, metric, unit in sensors:
        oasis.register_sensor(
            OWNER,
            {
                "sensor_id": sensor_id,
                "space_id": "gh-a",
                "metric": metric,
                "unit": unit,
                "source": "fixture-sensor",
            },
        )
    oasis.assign_plant(OWNER, plant_id, "gh-a")
    oasis.set_thresholds(
        OWNER,
        plant_id,
        [
            {"rule": "temperature", "minimum": 16, "maximum": 29, "evidence_note": "reviewed grower profile"},
            {"rule": "humidity", "minimum": 50, "maximum": 85},
            {"rule": "light", "minimum": 150, "maximum": 450},
            {"rule": "watering", "minimum": 25, "maximum": 75},
            {"rule": "ventilation", "maximum": 28, "target": 80},
        ],
    )
    return conservatory, oasis, plant_id


def _observe(oasis: OasisService, sensor: str, value: float | str, minute: int) -> None:
    oasis.observe(
        OWNER,
        {
            "sensor_id": sensor,
            "value": value,
            "observed_at": f"2026-08-07T14:{minute:02d}:00-07:00",
        },
    )


def test_environment_rules_emit_evidence_bound_recommendations(tmp_path: Path):
    _, oasis, plant_id = _configured(tmp_path)
    _observe(oasis, "temp", 31.0, 1)
    _observe(oasis, "rh", 88.0, 2)
    _observe(oasis, "light", 500.0, 3)
    _observe(oasis, "moisture", 18.0, 4)
    _observe(oasis, "vent", "closed", 5)

    result = oasis.evaluate(OWNER, plant_id, evaluated_at="2026-08-07T14:10:00-07:00")
    rules = {item["rule"] for item in result["recommendations"]}
    assert rules == {"temperature", "humidity", "light", "watering", "ventilation"}
    for recommendation in result["recommendations"]:
        assert recommendation["evidence_state"] == "measured"
        assert recommendation["evidence_observation_ids"]
        assert 0 <= recommendation["uncertainty"] <= 1
        assert recommendation["advisory_only"] is True
    assert result["autonomous_equipment_control"] is False
    assert result["medical_or_pesticide_prescribing"] is False


def test_missing_sensor_evidence_is_explicit_not_invented(tmp_path: Path):
    _, oasis, plant_id = _configured(tmp_path)
    result = oasis.evaluate(OWNER, plant_id, evaluated_at="2026-08-07T14:10:00-07:00")
    by_rule = {item["rule"]: item for item in result["recommendations"]}
    assert by_rule["temperature"]["evidence_state"] == "insufficient"
    assert by_rule["temperature"]["uncertainty"] == 1.0
    assert by_rule["watering"]["evidence_state"] == "insufficient"


def test_alert_acknowledgement_suppression_and_repeat_controls(tmp_path: Path):
    _, oasis, plant_id = _configured(tmp_path)
    _observe(oasis, "temp", 31.0, 1)
    first = oasis.evaluate(OWNER, plant_id, evaluated_at="2026-08-07T14:10:00-07:00")
    temperature = next(item for item in first["recommendations"] if item["rule"] == "temperature")
    oasis.acknowledge(
        OWNER,
        temperature["recommendation_id"],
        actor=OWNER,
        acknowledged_at="2026-08-07T14:11:00-07:00",
        suppress_until="2026-08-07T16:00:00-07:00",
        repeat_enabled=False,
    )
    repeated = oasis.evaluate(OWNER, plant_id, evaluated_at="2026-08-07T14:20:00-07:00")
    assert "temperature" not in {item["rule"] for item in repeated["recommendations"]}
    suppressed = [item for item in repeated["all_results"] if item.get("rule") == "temperature"]
    assert suppressed[0]["suppressed"] is True
    assert suppressed[0]["suppression_reason"] == "suppressed_until"


def test_intervention_handoff_becomes_conservatory_care_event_and_outcome(tmp_path: Path):
    conservatory, oasis, plant_id = _configured(tmp_path)
    _observe(oasis, "moisture", 15.0, 1)
    result = oasis.evaluate(OWNER, plant_id, evaluated_at="2026-08-07T14:10:00-07:00")
    watering = next(item for item in result["recommendations"] if item["rule"] == "watering")
    intervention = oasis.record_intervention(
        OWNER,
        watering["recommendation_id"],
        intervention_type="watering",
        performed_at="2026-08-07T14:15:00-07:00",
        actor=OWNER,
        notes="Watered after manual substrate check.",
    )
    assert intervention["conservatory_handoff"]["event"]["event_type"] == "treatment"
    events = conservatory.events(OWNER, plant_id)
    oasis_event = [item for item in events if item["details"].get("source") == "OASIS"]
    assert oasis_event[0]["details"]["intervention_type"] == "watering"

    outcome = oasis.record_outcome(
        OWNER,
        intervention["intervention"]["intervention_id"],
        recorded_at="2026-08-08T14:15:00-07:00",
        state="improved",
        notes="Substrate moisture restored without standing water.",
    )
    assert outcome["state"] == "improved"


def test_plant_assignment_must_match_private_conservatory_location(tmp_path: Path):
    conservatory = ConservatoryService(tmp_path / "conservatory")
    plant_id = _plant(conservatory)
    conservatory.create_location(
        OWNER,
        {"location_id": "shade-house", "label": "Shade House", "privacy": "private"},
    )
    oasis = OasisService(tmp_path / "oasis", conservatory=conservatory)
    oasis.configure_space(
        OWNER,
        {
            "space_id": "shade",
            "label": "Shade House",
            "conservatory_location_id": "shade-house",
        },
    )
    try:
        oasis.assign_plant(OWNER, plant_id, "shade")
    except ValueError as exc:
        assert "OASIS_PLANT_LOCATION_MISMATCH" in str(exc)
    else:
        raise AssertionError("OASIS must not silently reassign a plant location")


def test_protected_status_api_is_owner_scoped_and_non_authoritative(tmp_path: Path, monkeypatch):
    conservatory, oasis, _ = _configured(tmp_path)
    monkeypatch.setattr(api, "_service", lambda: oasis)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": OWNER, "auth_type": "test"}
    client = TestClient(app)

    status = client.get("/brain/mission-control/oasis/status")
    assert status.status_code == 200
    payload = status.json()
    assert payload["spaces"] == 1
    assert payload["sensors"] == 5
    assert payload["advisory_only"] is True
    assert payload["autonomous_equipment_control"] is False
    assert payload["medical_or_pesticide_prescribing"] is False
    assert payload["production_deployment_authorized"] is False
    assert conservatory.readiness(OWNER)["plants"] == 1
