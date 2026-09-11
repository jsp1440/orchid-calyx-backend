from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.conservatory import create_conservatory_router
from runtime.conservatory_events import ConservatoryEventStore
from runtime.conservatory_measurements import (
    ConservatoryMeasurementStore,
    MeasurementError,
)
from runtime.conservatory_store import ConservatoryStore


def _client(
    tmp_path: Path, *, events: ConservatoryEventStore | None = None
) -> TestClient:
    plants = ConservatoryStore(tmp_path)
    measurements = ConservatoryMeasurementStore(tmp_path)
    events = events or ConservatoryEventStore(tmp_path)
    app = FastAPI()
    app.include_router(
        create_conservatory_router(
            get_store=lambda: plants,
            get_measurements=lambda: measurements,
            get_events=lambda: events,
            require_owner=lambda: {"sub": "owner"},
        )
    )
    return TestClient(app)


def _plant(client: TestClient) -> str:
    response = client.post(
        "/api/conservatory/plants",
        json={"display_name": "Phragmipedium kovachii AM1"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_measurement_endpoint_preserves_observed_unit_and_evidence_boundary(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    plant_id = _plant(client)

    response = client.post(
        f"/api/conservatory/plants/{plant_id}/measurements",
        json={
            "trait": "flower_horizontal_span",
            "value": 4.2,
            "unit": "in",
            "method": "ruler",
            "observed_at": "2026-09-08",
            "note": "AM1 flower",
        },
    )

    assert response.status_code == 201
    record = response.json()
    assert record["value"] == 4.2
    assert record["unit"] == "in"
    assert record["is_scientific_evidence"] is False

    ledger = client.get(f"/api/conservatory/plants/{plant_id}/measurements")
    assert ledger.status_code == 200
    assert ledger.json()["measurements"] == [record]
    assert ledger.json()["is_scientific_evidence"] is False


def test_correction_appends_and_preserves_original_record(tmp_path: Path) -> None:
    store = ConservatoryMeasurementStore(tmp_path)
    original = store.record(
        plant_id="plant-1",
        trait="pouch_height",
        value=2.2,
        unit="in",
        method="caliper",
        observed_at="2026-09-01",
    )
    correction = store.record(
        plant_id="plant-1",
        trait="pouch_height",
        value=2.3,
        unit="in",
        method="caliper",
        observed_at="2026-09-01",
        supersedes_id=original["id"],
    )

    ledger = store.ledger("plant-1")
    assert ledger["count"] == 2
    assert ledger["standing_count"] == 1
    assert ledger["measurements"][0]["id"] == original["id"]
    assert ledger["measurements"][0]["superseded_by_id"] == correction["id"]
    assert ledger["measurements"][1]["supersedes_id"] == original["id"]


def test_measurement_vocabulary_fails_closed(tmp_path: Path) -> None:
    store = ConservatoryMeasurementStore(tmp_path)

    for values, code in [
        (
            {
                "trait": "flower_horizontal_span",
                "value": 4.2,
                "unit": "furlong",
                "method": "ruler",
            },
            "UNIT_NOT_ALLOWED_FOR_TRAIT",
        ),
        (
            {
                "trait": "guess",
                "value": 4.2,
                "unit": "in",
                "method": "ruler",
            },
            "TRAIT_UNRECOGNISED",
        ),
        (
            {
                "trait": "flower_count",
                "value": 1.5,
                "unit": "count",
                "method": "manual_count",
            },
            "COUNT_MUST_BE_AN_INTEGER",
        ),
    ]:
        try:
            store.record(
                plant_id="plant-1",
                observed_at="2026-09-08",
                **values,
            )
        except MeasurementError as exc:
            assert str(exc) == code
        else:
            raise AssertionError(f"expected {code}")


def test_scientific_evidence_promotion_is_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    plant_id = _plant(client)

    response = client.post(
        f"/api/conservatory/plants/{plant_id}/measurements",
        json={
            "trait": "petal_length",
            "value": 4.8,
            "unit": "in",
            "method": "ruler",
            "observed_at": "2026-09-08",
            "is_scientific_evidence": True,
        },
    )

    assert response.status_code == 422
    ledger = client.get(f"/api/conservatory/plants/{plant_id}/measurements")
    assert ledger.json()["count"] == 0


def test_measurement_routes_require_an_existing_plant(tmp_path: Path) -> None:
    client = _client(tmp_path)
    missing = "missing-plant"

    get_response = client.get(f"/api/conservatory/plants/{missing}/measurements")
    post_response = client.post(
        f"/api/conservatory/plants/{missing}/measurements",
        json={
            "trait": "plant_height",
            "value": 20,
            "unit": "cm",
            "method": "measuring_tape",
            "observed_at": "2026-09-08",
        },
    )

    assert get_response.status_code == 404
    assert post_response.status_code == 404


def test_flowering_binding_rejects_nonflowering_event(tmp_path: Path) -> None:
    events = ConservatoryEventStore(tmp_path)
    client = _client(tmp_path, events=events)
    plant_id = _plant(client)
    watered = events.record(
        plant_id=plant_id,
        kind="watered",
        occurred_at="2026-09-07",
    )
    flowering = events.record(
        plant_id=plant_id,
        kind="flowering_observed",
        occurred_at="2026-09-08",
    )
    payload = {
        "trait": "flower_vertical_span",
        "value": 3.9,
        "unit": "in",
        "method": "ruler",
        "observed_at": "2026-09-08",
        "flowering_event_id": watered["id"],
    }

    rejected = client.post(
        f"/api/conservatory/plants/{plant_id}/measurements",
        json=payload,
    )
    assert rejected.status_code == 404
    assert rejected.json()["detail"]["code"] == "FLOWERING_EVENT_NOT_FOUND_FOR_PLANT"

    payload["flowering_event_id"] = flowering["id"]
    accepted = client.post(
        f"/api/conservatory/plants/{plant_id}/measurements",
        json=payload,
    )
    assert accepted.status_code == 201
    assert accepted.json()["flowering_event_id"] == flowering["id"]
