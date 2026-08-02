from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.taxonomy_releases import create_taxonomy_release_router
from runtime.world_plants_release_store import WorldPlantsReleaseStore


def _payload() -> bytes:
    header = "|".join(str(index) for index in range(13))
    row = "|".join(
        [
            "S",
            "123",
            "Cattleya testensis Author",
            "lit",
            "",
            "Brazil",
            "= Test synonym",
            "",
            "",
            "",
            "photo.jpg",
            "landscape",
            "Photographer",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
        ]
    )
    return f"{header}\n{row}\n".encode()


def test_store_is_checksum_idempotent(tmp_path):
    store = WorldPlantsReleaseStore(tmp_path)
    first = store.inspect_and_store(
        _payload(),
        filename="release.csv",
        version_label="26-08",
        acquired_at="2026-08-02",
    )
    second = store.inspect_and_store(
        _payload(),
        filename="release.csv",
        version_label="26-08",
        acquired_at="2026-08-02",
    )
    assert first["release_id"] == second["release_id"]
    assert first["inspection"]["rows"] == 1
    assert first["automatic_promotion"] is False
    assert len(store.list_reports()) == 1


def test_upload_and_report_routes(tmp_path):
    store = WorldPlantsReleaseStore(tmp_path)
    app = FastAPI()
    app.include_router(
        create_taxonomy_release_router(lambda: store, lambda: {"actor": "test-owner"})
    )
    client = TestClient(app)

    response = client.post(
        "/api/mission-control/taxonomy/releases/inspect",
        files={"file": ("release.csv", _payload(), "text/csv")},
        data={"version_label": "26-08", "acquired_at": "2026-08-02"},
    )
    assert response.status_code == 200
    release_id = response.json()["release_id"]

    listing = client.get("/api/mission-control/taxonomy/releases")
    assert listing.status_code == 200
    assert listing.json()["releases"][0]["release_id"] == release_id

    detail = client.get(f"/api/mission-control/taxonomy/releases/{release_id}")
    assert detail.status_code == 200
    assert detail.json()["canonical_promotion"].startswith("blocked_")
