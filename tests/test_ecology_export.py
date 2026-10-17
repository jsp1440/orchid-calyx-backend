from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ecology_export.routes import router
from app.security import verify_owner_or_api_key

# Build a minimal app that includes only the ecology export router,
# with the owner-gate dependency overridden so tests run without credentials.
_app = FastAPI()
_app.include_router(router)
_app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test-owner"}

client = TestClient(_app)


def test_export_all_records():
    response = client.get("/api/ecology/export")
    assert response.status_code == 200
    data = response.json()
    assert "records" in data
    assert len(data["records"]) > 0
    assert data["total"] >= len(data["records"])


def test_export_filter_by_habitat():
    response = client.get("/api/ecology/export?habitat_type=EPIPHYTIC")
    assert response.status_code == 200
    data = response.json()
    for record in data["records"]:
        assert record["habitat_type"] == "EPIPHYTIC"


def test_export_pagination():
    response_all = client.get("/api/ecology/export")
    all_data = response_all.json()
    total = all_data["total"]

    if total >= 2:
        response_page = client.get("/api/ecology/export?limit=1&offset=1")
        assert response_page.status_code == 200
        page_data = response_page.json()
        assert page_data["limit"] == 1
        assert page_data["offset"] == 1
        assert len(page_data["records"]) <= 1


def test_export_single_species():
    known_taxon = "Cattleya labiata"
    response = client.get(f"/api/ecology/export/species/{known_taxon}")
    assert response.status_code == 200
    data = response.json()
    assert data["taxon_name"] == known_taxon


def test_export_species_not_found():
    response = client.get("/api/ecology/export/species/Nonexistent orchidus")
    assert response.status_code == 404


def test_export_format_field():
    response = client.get("/api/ecology/export")
    assert response.status_code == 200
    data = response.json()
    assert data["format"] == "JSON"
