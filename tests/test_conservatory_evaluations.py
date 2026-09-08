from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.conservatory import create_conservatory_router
from runtime.conservatory_evaluations import (
    ConservatoryEvaluationStore,
    EvaluationError,
)
from runtime.conservatory_store import ConservatoryStore


def _client(tmp_path: Path) -> TestClient:
    plants = ConservatoryStore(tmp_path)
    evaluations = ConservatoryEvaluationStore(tmp_path)
    app = FastAPI()
    app.include_router(
        create_conservatory_router(
            get_store=lambda: plants,
            get_evaluations=lambda: evaluations,
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


def test_evaluation_endpoint_records_am1_without_promoting_observations(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    plant_id = _plant(client)
    identity = "Phragmipedium kovachii 'Daniela' × 'Maria'"

    response = client.post(
        f"/api/conservatory/plants/{plant_id}/evaluations",
        json={
            "cultivated_identity": identity,
            "species_consulted": "Phragmipedium kovachii",
            "relationship": "cross_within_species",
            "location_kind": "greenhouse",
            "standing_observations": ["Leaves appear firm"],
            "alternatives_considered": ["shade_house"],
        },
    )

    assert response.status_code == 201
    evaluation = response.json()
    assert evaluation["cultivated_identity"] == identity
    assert evaluation["species_consulted"] == "Phragmipedium kovachii"
    assert evaluation["is_scientific_evidence"] is False
    assert evaluation["observations_are_evidence"] is False

    history = client.get(f"/api/conservatory/plants/{plant_id}/evaluations")
    assert history.status_code == 200
    assert history.json()["evaluations"] == [evaluation]
    assert history.json()["is_scientific_evidence"] is False
    assert history.json()["observations_are_evidence"] is False


def test_later_evaluation_never_supersedes_earlier_history(tmp_path: Path) -> None:
    store = ConservatoryEvaluationStore(tmp_path)
    values = {
        "plant_id": "plant-1",
        "cultivated_identity": "Phragmipedium kovachii",
        "species_consulted": "Phragmipedium kovachii",
        "relationship": "species",
        "location_kind": "greenhouse",
        "standing_observations": [],
        "alternatives_considered": [],
    }
    first = store.record(**values)
    second = store.record(
        **{
            **values,
            "location_kind": "shade_house",
            "standing_observations": ["A later independent assessment"],
        }
    )

    history = store.history("plant-1")
    assert history["count"] == 2
    assert history["evaluations"][0] == first
    assert history["evaluations"][1] == second
    assert "supersedes_id" not in first
    assert "superseded_by_id" not in first


def test_interspecific_cross_refuses_first_parent_as_species(tmp_path: Path) -> None:
    store = ConservatoryEvaluationStore(tmp_path)

    try:
        store.record(
            plant_id="plant-1",
            cultivated_identity="Phragmipedium kovachii × Phragmipedium humboldtii",
            species_consulted="Phragmipedium kovachii",
            relationship="species",
            location_kind="greenhouse",
            standing_observations=[],
            alternatives_considered=[],
        )
    except EvaluationError as exc:
        assert str(exc) == "RELATIONSHIP_CONTRADICTS_CULTIVATED_IDENTITY"
    else:
        raise AssertionError("interspecific first-parent fallback was accepted")

    accepted = store.record(
        plant_id="plant-1",
        cultivated_identity="Phragmipedium kovachii × Phragmipedium humboldtii",
        species_consulted=None,
        relationship="none",
        location_kind="greenhouse",
        standing_observations=[],
        alternatives_considered=["No defensible species binding"],
    )
    assert accepted["species_consulted"] is None
    assert accepted["relationship"] == "none"


def test_location_name_and_evidence_promotion_fields_fail_closed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    plant_id = _plant(client)
    base = {
        "cultivated_identity": "Phragmipedium kovachii",
        "species_consulted": "Phragmipedium kovachii",
        "relationship": "species",
        "location_kind": "greenhouse",
        "standing_observations": [],
        "alternatives_considered": [],
    }

    for forbidden in [
        {"location_name": "private greenhouse bench 2"},
        {"is_scientific_evidence": True},
        {"observations_are_evidence": True},
        {"supersedes_id": "earlier-evaluation"},
    ]:
        response = client.post(
            f"/api/conservatory/plants/{plant_id}/evaluations",
            json={**base, **forbidden},
        )
        assert response.status_code == 422

    history = client.get(f"/api/conservatory/plants/{plant_id}/evaluations")
    assert history.json()["count"] == 0


def test_evaluation_routes_require_an_existing_plant(tmp_path: Path) -> None:
    client = _client(tmp_path)
    missing = "missing-plant"

    get_response = client.get(f"/api/conservatory/plants/{missing}/evaluations")
    post_response = client.post(
        f"/api/conservatory/plants/{missing}/evaluations",
        json={
            "cultivated_identity": "Phragmipedium kovachii",
            "species_consulted": "Phragmipedium kovachii",
            "relationship": "species",
            "location_kind": "unknown",
        },
    )

    assert get_response.status_code == 404
    assert post_response.status_code == 404
