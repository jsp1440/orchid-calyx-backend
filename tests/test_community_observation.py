"""
Focused tests for Journey 10: Community Observation + Moderation Queue.

Covers:
- Submit observation → 200, state=SUBMITTED
- Get observation → 200
- List observations → 200, list type
- Moderate approve → 200, state=APPROVED
- Moderate reject → 200, state=REJECTED
- Moderate quarantine → 200, state=QUARANTINED
- Invalid moderation state (SUBMITTED) → 422
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.community_observation.models import ModerationState
from app.community_observation.routes import router, _store


@pytest.fixture(autouse=True)
def clear_store():
    """Ensure in-memory store is empty before each test."""
    _store.clear()
    yield
    _store.clear()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


SAMPLE_PAYLOAD = {
    "taxon_name_verbatim": "Cattleya labiata",
    "location_verbatim": "Serra do Mar, Brazil",
    "observation_date": str(date(2026, 6, 15)),
    "epistemic_label": "PROBABLE",
    "notes": "Saw two plants in flower on a rocky outcrop.",
    "evidence_media_ids": ["11111111-1111-1111-1111-111111111111"],
}


def _submit(client) -> dict:
    resp = client.post("/api/community/observations", json=SAMPLE_PAYLOAD)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Test: submit observation
# ---------------------------------------------------------------------------

def test_submit_observation_returns_submitted_state(client):
    data = _submit(client)
    assert "id" in data
    assert data["moderation_state"] == ModerationState.SUBMITTED.value
    assert "created_at" in data


# ---------------------------------------------------------------------------
# Test: get observation
# ---------------------------------------------------------------------------

def test_get_observation_returns_200(client):
    submitted = _submit(client)
    obs_id = submitted["id"]
    resp = client.get(f"/api/community/observations/{obs_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == obs_id
    assert body["taxon_name_verbatim"] == "Cattleya labiata"
    assert body["epistemic_label"] == "PROBABLE"


# ---------------------------------------------------------------------------
# Test: list observations
# ---------------------------------------------------------------------------

def test_list_observations_returns_200_and_list(client):
    _submit(client)
    _submit(client)
    resp = client.get("/api/community/observations")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["items"], list)
    assert body["total"] == 2


# ---------------------------------------------------------------------------
# Test: moderate approve
# ---------------------------------------------------------------------------

def test_moderate_approve_sets_approved_state(client):
    submitted = _submit(client)
    obs_id = submitted["id"]
    decision = {
        "observation_id": obs_id,
        "new_state": "APPROVED",
        "reason": "Clear photograph, reliable species ID.",
    }
    resp = client.patch(f"/api/community/observations/{obs_id}/moderate", json=decision)
    assert resp.status_code == 200, resp.text
    assert resp.json()["moderation_state"] == ModerationState.APPROVED.value


# ---------------------------------------------------------------------------
# Test: moderate reject
# ---------------------------------------------------------------------------

def test_moderate_reject_sets_rejected_state(client):
    submitted = _submit(client)
    obs_id = submitted["id"]
    decision = {
        "observation_id": obs_id,
        "new_state": "REJECTED",
        "reason": "Insufficient evidence; plant not visible.",
    }
    resp = client.patch(f"/api/community/observations/{obs_id}/moderate", json=decision)
    assert resp.status_code == 200, resp.text
    assert resp.json()["moderation_state"] == ModerationState.REJECTED.value


# ---------------------------------------------------------------------------
# Test: moderate quarantine
# ---------------------------------------------------------------------------

def test_moderate_quarantine_sets_quarantined_state(client):
    submitted = _submit(client)
    obs_id = submitted["id"]
    decision = {
        "observation_id": obs_id,
        "new_state": "QUARANTINED",
        "reason": "Pending expert review.",
    }
    resp = client.patch(f"/api/community/observations/{obs_id}/moderate", json=decision)
    assert resp.status_code == 200, resp.text
    assert resp.json()["moderation_state"] == ModerationState.QUARANTINED.value


# ---------------------------------------------------------------------------
# Test: invalid moderation state (SUBMITTED) → 422
# ---------------------------------------------------------------------------

def test_moderate_submitted_state_returns_422(client):
    submitted = _submit(client)
    obs_id = submitted["id"]
    decision = {
        "observation_id": obs_id,
        "new_state": "SUBMITTED",
        "reason": "Attempting to reset to SUBMITTED.",
    }
    resp = client.patch(f"/api/community/observations/{obs_id}/moderate", json=decision)
    assert resp.status_code == 422
