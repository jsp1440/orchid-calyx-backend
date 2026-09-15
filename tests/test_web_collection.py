from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web_collection.routes import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)


def test_search_all() -> None:
    resp = client.get("/api/collection/search")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["entries"]) == 5
    assert data["query"] == ""


def test_search_by_name() -> None:
    resp = client.get("/api/collection/search", params={"q": "orchid"})
    assert resp.status_code == 200
    data = resp.json()
    # "Vanilla Orchid", "Moon Orchid", "White Moth Orchid", "Vampire Orchid", "Dracula Orchid"
    # common_names contain "Orchid" for multiple entries; at least 1 must match
    assert data["total"] >= 1
    for entry in data["entries"]:
        combined = (
            entry["taxon_name"]
            + " "
            + " ".join(entry["common_names"])
            + " "
            + (entry["family"] or "")
            + " "
            + (entry["genus"] or "")
        )
        assert "orchid" in combined.lower()


def test_search_no_results() -> None:
    resp = client.get("/api/collection/search", params={"q": "zzznomatch"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["entries"] == []


def test_browse_all() -> None:
    resp = client.get("/api/collection/browse")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    assert len(data["entries"]) == 5


def test_browse_by_family() -> None:
    resp = client.get("/api/collection/browse", params={"family": "Orchidaceae"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 5
    for entry in data["entries"]:
        assert entry["family"] == "Orchidaceae"


def test_browse_by_genus() -> None:
    resp = client.get("/api/collection/browse", params={"genus": "Phalaenopsis"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["entries"][0]["genus"] == "Phalaenopsis"


def test_get_species() -> None:
    resp = client.get("/api/collection/species/orch-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["taxon_id"] == "orch-001"
    assert data["taxon_name"] == "Phalaenopsis amabilis"


def test_get_species_not_found() -> None:
    resp = client.get("/api/collection/species/unknown-99999")
    assert resp.status_code == 404
