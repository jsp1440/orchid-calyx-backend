"""Tests for Journey 11: community share module with audience-scoped permissions.

Covers:
  - Create PUBLIC share → 201, share_token present
  - GET PUBLIC share → 200
  - Create MEMBERS_ONLY share, GET without member header → 403
  - Create MEMBERS_ONLY share, GET with X-Member: true → 200
  - Create PRIVATE share, GET with wrong requester → 403
  - Create PRIVATE share, GET with correct X-Requester-Id → 200
  - List shares → 200
  - DELETE share → 200, is_active=False
  - GET deleted share → 404
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.community_share.routes import _store, router


@pytest.fixture(autouse=True)
def clear_store():
    """Ensure a clean in-memory store for every test."""
    _store.clear()
    yield
    _store.clear()


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_share(client: TestClient, audience: str, sharer: str = "user-abc") -> dict:
    payload = {
        "artifact_id": "obs-001",
        "artifact_kind": "OBSERVATION",
        "audience": audience,
        "sharer_auth_subject": sharer,
    }
    response = client.post("/api/community/shares", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_create_public_share_returns_201_with_token(client: TestClient):
    data = make_share(client, "PUBLIC")
    assert "share_token" in data
    assert data["share_token"]
    assert data["audience"] == "PUBLIC"
    assert data["is_active"] is True


def test_get_public_share_returns_200(client: TestClient):
    share = make_share(client, "PUBLIC")
    token = share["share_token"]
    resp = client.get(f"/api/community/shares/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["share_record"]["share_token"] == token
    assert body["artifact_preview"]["artifact_id"] == "obs-001"


def test_get_members_only_share_without_header_returns_403(client: TestClient):
    share = make_share(client, "MEMBERS_ONLY")
    token = share["share_token"]
    resp = client.get(f"/api/community/shares/{token}")
    assert resp.status_code == 403


def test_get_members_only_share_with_member_header_returns_200(client: TestClient):
    share = make_share(client, "MEMBERS_ONLY")
    token = share["share_token"]
    resp = client.get(f"/api/community/shares/{token}", headers={"X-Member": "true"})
    assert resp.status_code == 200
    assert resp.json()["share_record"]["audience"] == "MEMBERS_ONLY"


def test_get_private_share_with_wrong_requester_returns_403(client: TestClient):
    share = make_share(client, "PRIVATE", sharer="user-abc")
    token = share["share_token"]
    resp = client.get(
        f"/api/community/shares/{token}",
        headers={"X-Requester-Id": "user-xyz"},
    )
    assert resp.status_code == 403


def test_get_private_share_with_correct_requester_returns_200(client: TestClient):
    share = make_share(client, "PRIVATE", sharer="user-abc")
    token = share["share_token"]
    resp = client.get(
        f"/api/community/shares/{token}",
        headers={"X-Requester-Id": "user-abc"},
    )
    assert resp.status_code == 200
    assert resp.json()["share_record"]["audience"] == "PRIVATE"


def test_list_shares_returns_200(client: TestClient):
    make_share(client, "PUBLIC", sharer="user-list")
    make_share(client, "MEMBERS_ONLY", sharer="user-list")
    resp = client.get(
        "/api/community/shares",
        headers={"X-Requester-Id": "user-list"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_delete_share_returns_200_and_is_inactive(client: TestClient):
    share = make_share(client, "PUBLIC", sharer="user-del")
    token = share["share_token"]
    resp = client.delete(
        f"/api/community/shares/{token}",
        headers={"X-Requester-Id": "user-del"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False


def test_get_deleted_share_returns_404(client: TestClient):
    share = make_share(client, "PUBLIC", sharer="user-del")
    token = share["share_token"]
    # Delete it first
    client.delete(
        f"/api/community/shares/{token}",
        headers={"X-Requester-Id": "user-del"},
    )
    # Now attempt to GET
    resp = client.get(f"/api/community/shares/{token}")
    assert resp.status_code == 404
