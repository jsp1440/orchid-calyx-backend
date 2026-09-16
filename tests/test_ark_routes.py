"""Tests for ARK continuity state API — Journey 15."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ark.routes import _STUB_RUN_ID, router
from app.security import verify_owner_or_api_key


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.dependency_overrides[verify_owner_or_api_key] = lambda: None
    app.include_router(router)
    return TestClient(app)


def test_get_ark_status(client: TestClient) -> None:
    resp = client.get("/api/ark/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["overall_state"] == "VERIFIED"
    assert data["species_count"] == 42
    assert data["last_run_id"] == str(_STUB_RUN_ID)


def test_list_ark_runs(client: TestClient) -> None:
    resp = client.get("/api/ark/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) >= 1
    assert runs[0]["outcome"] == "SUCCESS"
    assert runs[0]["species_verified"] == 42


def test_get_ark_evidence(client: TestClient) -> None:
    resp = client.get(f"/api/ark/evidence/{_STUB_RUN_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["outcome"] == "SUCCESS"
    assert len(data["evidence_items"]) >= 1


def test_get_ark_evidence_not_found(client: TestClient) -> None:
    resp = client.get("/api/ark/evidence/00000000-0000-0000-0000-000000000099")
    assert resp.status_code == 404


def test_ark_status_continuity_state_enum(client: TestClient) -> None:
    resp = client.get("/api/ark/status")
    assert resp.json()["overall_state"] in {
        "DISCOVERED", "PROTECTED", "VERIFIED",
        "RESTORE_TESTED", "DEGRADED", "FAILED", "RECOVERING",
    }
