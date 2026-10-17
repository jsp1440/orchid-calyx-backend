from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.user_collection import routes as uc_routes
from app.user_collection.routes import _store


@pytest.fixture(autouse=True)
def clear_store():
    _store.clear()
    yield
    _store.clear()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(uc_routes.router)
    return TestClient(app)


def test_create_item(client: TestClient):
    resp = client.post(
        "/api/user-collection/items",
        json={"taxon_name_verbatim": "Phalaenopsis amabilis"},
        headers={"x-auth-subject": "user-a"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["taxon_name_verbatim"] == "Phalaenopsis amabilis"
    assert data["care_status"] == "UNKNOWN"
    assert data["user_auth_subject"] == "user-a"
    assert "id" in data


def test_list_items(client: TestClient):
    client.post(
        "/api/user-collection/items",
        json={"taxon_name_verbatim": "Cattleya labiata"},
        headers={"x-auth-subject": "user-a"},
    )
    resp = client.get(
        "/api/user-collection/items",
        headers={"x-auth-subject": "user-a"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["taxon_name_verbatim"] == "Cattleya labiata"


def test_list_items_user_isolation(client: TestClient):
    client.post(
        "/api/user-collection/items",
        json={"taxon_name_verbatim": "Dendrobium nobile"},
        headers={"x-auth-subject": "user-a"},
    )
    resp = client.get(
        "/api/user-collection/items",
        headers={"x-auth-subject": "user-b"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_get_item(client: TestClient):
    create_resp = client.post(
        "/api/user-collection/items",
        json={"taxon_name_verbatim": "Vanda coerulea"},
        headers={"x-auth-subject": "user-a"},
    )
    item_id = create_resp.json()["id"]
    resp = client.get(
        f"/api/user-collection/items/{item_id}",
        headers={"x-auth-subject": "user-a"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == item_id


def test_get_item_not_found(client: TestClient):
    resp = client.get(
        "/api/user-collection/items/00000000-0000-0000-0000-000000000000",
        headers={"x-auth-subject": "user-a"},
    )
    assert resp.status_code == 404


def test_patch_item(client: TestClient):
    create_resp = client.post(
        "/api/user-collection/items",
        json={"taxon_name_verbatim": "Oncidium sphacelatum"},
        headers={"x-auth-subject": "user-a"},
    )
    item_id = create_resp.json()["id"]
    resp = client.patch(
        f"/api/user-collection/items/{item_id}",
        json={"notes": "Repotted recently", "care_status": "THRIVING"},
        headers={"x-auth-subject": "user-a"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["notes"] == "Repotted recently"
    assert data["care_status"] == "THRIVING"
    assert data["taxon_name_verbatim"] == "Oncidium sphacelatum"


def test_delete_item(client: TestClient):
    create_resp = client.post(
        "/api/user-collection/items",
        json={"taxon_name_verbatim": "Masdevallia veitchiana"},
        headers={"x-auth-subject": "user-a"},
    )
    item_id = create_resp.json()["id"]
    del_resp = client.delete(
        f"/api/user-collection/items/{item_id}",
        headers={"x-auth-subject": "user-a"},
    )
    assert del_resp.status_code == 204
    get_resp = client.get(
        f"/api/user-collection/items/{item_id}",
        headers={"x-auth-subject": "user-a"},
    )
    assert get_resp.status_code == 404


def test_create_invalid_care_status(client: TestClient):
    resp = client.post(
        "/api/user-collection/items",
        json={"taxon_name_verbatim": "Zygopetalum mackayi", "care_status": "FLYING"},
        headers={"x-auth-subject": "user-a"},
    )
    assert resp.status_code == 422
