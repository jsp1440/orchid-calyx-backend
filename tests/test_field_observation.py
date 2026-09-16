"""
Focused tests for Journey 5: Field Observation Create/Manage.

Covers:
- Create observation → 200, curation_state=PENDING, epistemic_certainty=POSSIBLE
- Create with explicit epistemic_certainty=CONFIRMED → response has CONFIRMED
- Get created observation → 200
- List observations → 200, list type
- Attach photo → 200, has storage_key
- Get taxon suggestion → 200, has ai_taxon_suggestion field
- Get unknown observation → 404
- Create with invalid epistemic_certainty → 422
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.field_observation.models import (
    EpistemicCertaintyLabel,
    ObservationCurationState,
)
from app.field_observation.routes import _observations, _photos, router


@pytest.fixture(autouse=True)
def clear_stores():
    """Ensure in-memory stores are empty before and after each test."""
    _observations.clear()
    _photos.clear()
    yield
    _observations.clear()
    _photos.clear()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


SAMPLE_PAYLOAD = {
    "observer_id": "auth-subject-opaque-token-abc123",
    "observed_at": "2026-06-15T10:30:00",
    "location_name": "Serra dos Órgãos, Brazil",
    "taxon_hint": "Laelia purpurata",
    "observation_text": "Two plants in flower on a granite outcrop, approx 1400m elevation.",
}


def _create(client, **overrides) -> dict:
    payload = {**SAMPLE_PAYLOAD, **overrides}
    resp = client.post("/api/field-observations", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Test: create observation with defaults
# ---------------------------------------------------------------------------

def test_create_observation_defaults_to_pending_and_possible(client):
    data = _create(client)
    assert "id" in data
    assert data["curation_state"] == ObservationCurationState.PENDING.value
    assert data["epistemic_certainty"] == EpistemicCertaintyLabel.POSSIBLE.value
    assert data["observer_id"] == "auth-subject-opaque-token-abc123"
    assert data["taxon_hint"] == "Laelia purpurata"
    assert data["ai_taxon_suggestion"] is None
    assert data["photo_count"] == 0


# ---------------------------------------------------------------------------
# Test: create with explicit epistemic_certainty=CONFIRMED
# ---------------------------------------------------------------------------

def test_create_observation_with_confirmed_certainty(client):
    data = _create(client, epistemic_certainty="CONFIRMED")
    assert data["epistemic_certainty"] == EpistemicCertaintyLabel.CONFIRMED.value
    assert data["curation_state"] == ObservationCurationState.PENDING.value


# ---------------------------------------------------------------------------
# Test: get created observation
# ---------------------------------------------------------------------------

def test_get_observation_returns_200(client):
    created = _create(client)
    obs_id = created["id"]
    resp = client.get(f"/api/field-observations/{obs_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == obs_id
    assert body["observer_id"] == "auth-subject-opaque-token-abc123"
    assert body["taxon_hint"] == "Laelia purpurata"


# ---------------------------------------------------------------------------
# Test: list observations
# ---------------------------------------------------------------------------

def test_list_observations_returns_200_and_list(client):
    _create(client)
    _create(client, observer_id="auth-subject-other-xyz")
    resp = client.get("/api/field-observations")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["items"], list)
    assert body["total"] == 2


# ---------------------------------------------------------------------------
# Test: attach photo
# ---------------------------------------------------------------------------

def test_attach_photo_returns_200_with_storage_key(client):
    created = _create(client)
    obs_id = created["id"]
    photo_payload = {
        "storage_key": "photos/2026/06/laelia-purpurata-001.jpg",
        "content_hash": "a" * 64,  # 64-char SHA-256 hex stub
        "photographer_id": "auth-photographer-opaque-99",
        "license": "CC-BY-4.0",
    }
    resp = client.post(f"/api/field-observations/{obs_id}/photos", json=photo_payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "id" in body
    assert body["observation_id"] == obs_id
    assert body["storage_key"] == "photos/2026/06/laelia-purpurata-001.jpg"
    assert "created_at" in body


# ---------------------------------------------------------------------------
# Test: get taxon suggestion (NO_API_MODE stub)
# ---------------------------------------------------------------------------

def test_taxon_suggestion_returns_200_with_suggestion_field(client):
    created = _create(client)
    obs_id = created["id"]
    resp = client.post(f"/api/field-observations/{obs_id}/taxon-suggestion")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "ai_taxon_suggestion" in body
    assert body["ai_taxon_suggestion"] == "[AI suggestion pending — NO_API_MODE]"
    assert body["observation_id"] == obs_id
    assert body["ai_suggestion_confidence"] is None
    assert "requested_at" in body


# ---------------------------------------------------------------------------
# Test: get unknown observation → 404
# ---------------------------------------------------------------------------

def test_get_unknown_observation_returns_404(client):
    resp = client.get("/api/field-observations/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Test: create with invalid epistemic_certainty → 422
# ---------------------------------------------------------------------------

def test_create_with_invalid_epistemic_certainty_returns_422(client):
    payload = {**SAMPLE_PAYLOAD, "epistemic_certainty": "VERY_SURE"}
    resp = client.post("/api/field-observations", json=payload)
    assert resp.status_code == 422
