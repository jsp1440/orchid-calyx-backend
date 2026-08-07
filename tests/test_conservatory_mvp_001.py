from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.conservatory import create_conservatory_router
from runtime.conservatory_store import ConservatoryStore


def _client(tmp_path: Path) -> TestClient:
    store = ConservatoryStore(tmp_path)
    app = FastAPI()
    app.include_router(
        create_conservatory_router(
            get_store=lambda: store,
            require_owner=lambda: {"sub": "owner"},
        )
    )
    return TestClient(app)


def test_create_list_get_and_label_manifest(tmp_path: Path):
    client = _client(tmp_path)

    created = client.post(
        "/api/conservatory/plants",
        json={
            "display_name": "Cattleya skinneri alba 'Snow'",
            "accepted_scientific_name": "Cattleya skinneri",
            "location": "Greenhouse bench 2",
            "notes": "FCOS collection",
        },
    )
    assert created.status_code == 201
    plant = created.json()
    assert plant["accession_number"].startswith("OC-")
    assert plant["qr_identifier"] == f"calyx:plant:{plant['id']}"

    listed = client.get("/api/conservatory/plants")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1

    fetched = client.get(f"/api/conservatory/plants/{plant['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["display_name"] == plant["display_name"]

    manifest = client.post(
        "/api/conservatory/labels/manifest",
        json={"plant_ids": [plant["id"]]},
    )
    assert manifest.status_code == 200
    assert manifest.json()["count"] == 1
    assert manifest.json()["labels"][0]["accession_number"] == plant["accession_number"]


def test_accessions_increment_and_store_persists(tmp_path: Path):
    store = ConservatoryStore(tmp_path)
    first = store.create(display_name="Phalaenopsis bellina")
    second = store.create(display_name="Dendrobium kingianum")

    assert first["accession_number"][:-4] == second["accession_number"][:-4]
    assert (
        int(second["accession_number"][-4:]) == int(first["accession_number"][-4:]) + 1
    )
    assert ConservatoryStore(tmp_path).get(first["id"]) == first


def test_invalid_name_is_rejected(tmp_path: Path):
    client = _client(tmp_path)
    response = client.post("/api/conservatory/plants", json={"display_name": "x"})
    assert response.status_code == 422
