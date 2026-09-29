"""Journey 5 — field observation create/manage: durable, gated, locality fail-closed."""

from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.field_observation import service as observation_service
from app.field_observation.routes import router
from app.field_observation.schemas import SCIENTIFIC_STATUS
from app.security import verify_owner_or_api_key

OWNER_AUTH = {"actor": "owner@example.test", "auth_type": "owner_session"}
API_KEY_AUTH = {"actor": "backend_api_key", "auth_type": "api_key"}

SAMPLE = {
    "observed_at": "2026-06-15T10:30:00Z",
    "note": "Two plants in flower on a granite outcrop; one visited by a small bee.",
    "taxon_hint": "Laelia purpurata",
    "locality_visibility": "research_restricted",
    "media": [{"name": "IMG_0001.jpg", "size": 2048, "type": "image/jpeg"}],
}

PHOTO = {
    "storage_key": "field/2026/06/abc123",
    "content_hash": hashlib.sha256(b"photo-bytes").hexdigest(),
    "photographer_subject": "member-token-1",
    "license": "CC-BY-4.0",
    "provenance": {"device": "phone", "captured_offline": True},
}


@pytest.fixture(autouse=True)
def isolated_store():
    observation_service.configure_store(observation_service.memory_store())
    yield
    observation_service.configure_store(None)


def _app(auth: dict | None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    if auth is not None:
        app.dependency_overrides[verify_owner_or_api_key] = lambda: dict(auth)
    return app


@pytest.fixture()
def owner() -> TestClient:
    return TestClient(_app(OWNER_AUTH))


@pytest.fixture()
def service_client() -> TestClient:
    return TestClient(_app(API_KEY_AUTH))


@pytest.fixture()
def anonymous(monkeypatch) -> TestClient:
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    return TestClient(_app(None))


def _member(client: TestClient, subject: str) -> dict[str, str]:
    return {"X-Auth-Subject": subject}


# -- create -----------------------------------------------------------------------------


def test_create_records_observer_report_without_promotion(owner):
    resp = owner.post("/api/field-observations", json=SAMPLE)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["id"].startswith("fo-")
    assert body["observer_subject"] == OWNER_AUTH["actor"]
    assert body["curation_state"] == "PENDING"
    assert body["epistemic_certainty"] == "POSSIBLE"
    assert body["scientific_status"] == SCIENTIFIC_STATUS
    assert body["knowledge_graph_publication"] == "blocked_pending_human_scientific_review"
    assert body["hypotheses_path"] == f"/api/field-observations/{body['id']}/hypotheses"
    assert body["locality_visibility"] == "research_restricted"
    assert body["media"] == SAMPLE["media"]
    assert body["photo_count"] == 0


def test_create_is_idempotent_per_observer_and_client_draft(owner):
    payload = {**SAMPLE, "client_draft_id": "draft-42"}
    first = owner.post("/api/field-observations", json=payload)
    second = owner.post("/api/field-observations", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    listing = owner.get("/api/field-observations").json()
    assert listing["total"] == 1


def test_same_client_draft_from_another_observer_is_a_different_observation(service_client):
    payload = {**SAMPLE, "client_draft_id": "draft-42"}
    a = service_client.post("/api/field-observations", json=payload, headers=_member(service_client, "member-a"))
    b = service_client.post("/api/field-observations", json=payload, headers=_member(service_client, "member-b"))
    assert a.status_code == 201 and b.status_code == 201
    assert a.json()["id"] != b.json()["id"]


@pytest.mark.parametrize(
    "locality_payload",
    [
        {"latitude": -22.45, "longitude": -43.0},
        {"location": "the ridge above the reservoir"},
        {"media": [{"name": "x.jpg", "size": 1, "type": "image/jpeg", "gps": "-22,-43"}]},
    ],
)
def test_create_rejects_protected_locality_anywhere(owner, locality_payload):
    resp = owner.post("/api/field-observations", json={**SAMPLE, **locality_payload})
    assert resp.status_code == 422
    assert owner.get("/api/field-observations").json()["total"] == 0


def test_create_requires_a_note_and_bounded_media(owner):
    assert owner.post("/api/field-observations", json={**SAMPLE, "note": ""}).status_code == 422
    too_many = {**SAMPLE, "media": [SAMPLE["media"][0]] * 21}
    assert owner.post("/api/field-observations", json=too_many).status_code == 422


# -- auth boundary ----------------------------------------------------------------------


def test_anonymous_callers_are_refused_everywhere(anonymous):
    assert anonymous.post("/api/field-observations", json=SAMPLE).status_code == 401
    assert anonymous.get("/api/field-observations").status_code == 401
    assert anonymous.get("/api/field-observations/fo-000000000000000000000000").status_code == 401
    assert anonymous.post("/api/field-observations/fo-0/photos", json=PHOTO).status_code == 401
    assert anonymous.post("/api/field-observations/fo-0/curation", json={"state": "CURATED"}).status_code == 401


def test_member_subject_must_be_opaque_not_email(service_client):
    resp = service_client.post(
        "/api/field-observations", json=SAMPLE, headers=_member(service_client, "someone@example.org")
    )
    assert resp.status_code == 422


def test_members_are_scoped_to_their_own_observations(service_client, owner):
    mine = service_client.post("/api/field-observations", json=SAMPLE, headers=_member(service_client, "member-a"))
    theirs = service_client.post("/api/field-observations", json=SAMPLE, headers=_member(service_client, "member-b"))
    assert mine.status_code == 201 and theirs.status_code == 201
    their_id = theirs.json()["id"]
    hdr = _member(service_client, "member-a")

    assert service_client.get(f"/api/field-observations/{their_id}", headers=hdr).status_code == 404
    assert service_client.get(f"/api/field-observations/{their_id}/photos", headers=hdr).status_code == 404
    assert service_client.post(f"/api/field-observations/{their_id}/photos", json=PHOTO, headers=hdr).status_code == 404
    assert (
        service_client.get("/api/field-observations", params={"observer_subject": "member-b"}, headers=hdr).status_code
        == 403
    )
    own_listing = service_client.get("/api/field-observations", headers=hdr).json()
    assert own_listing["observer_subject"] == "member-a"
    assert [item["id"] for item in own_listing["items"]] == [mine.json()["id"]]

    # The owner session sees both observers.
    assert owner.get(f"/api/field-observations/{their_id}").status_code == 200
    assert owner.get("/api/field-observations", params={"observer_subject": "member-b"}).json()["total"] == 1


def test_members_cannot_curate(service_client):
    created = service_client.post("/api/field-observations", json=SAMPLE, headers=_member(service_client, "member-a"))
    resp = service_client.post(
        f"/api/field-observations/{created.json()['id']}/curation",
        json={"state": "CURATED"},
        headers=_member(service_client, "member-a"),
    )
    assert resp.status_code == 403


# -- curation -----------------------------------------------------------------------------


def test_owner_curation_records_actor_and_rejects_pending_target(owner):
    obs_id = owner.post("/api/field-observations", json=SAMPLE).json()["id"]
    bad = owner.post(f"/api/field-observations/{obs_id}/curation", json={"state": "PENDING"})
    assert bad.status_code == 422
    good = owner.post(
        f"/api/field-observations/{obs_id}/curation",
        json={"state": "FLAGGED", "reason": "Identification uncertain; needs a second look."},
    )
    assert good.status_code == 200, good.text
    body = good.json()
    assert body["curation_state"] == "FLAGGED"
    assert body["curated_by"] == OWNER_AUTH["actor"]
    assert body["curation_reason"].startswith("Identification uncertain")
    assert body["scientific_status"] == SCIENTIFIC_STATUS
    assert owner.get("/api/field-observations", params={"curation_state": "FLAGGED"}).json()["total"] == 1


def test_unknown_observation_is_404(owner):
    assert owner.get("/api/field-observations/fo-does-not-exist").status_code == 404
    assert owner.post("/api/field-observations/fo-does-not-exist/photos", json=PHOTO).status_code == 404
    assert owner.post("/api/field-observations/fo-does-not-exist/curation", json={"state": "CURATED"}).status_code == 404


# -- photos -------------------------------------------------------------------------------


def test_photo_attach_carries_provenance_and_is_idempotent_by_hash(owner):
    obs_id = owner.post("/api/field-observations", json=SAMPLE).json()["id"]
    first = owner.post(f"/api/field-observations/{obs_id}/photos", json=PHOTO)
    assert first.status_code == 201, first.text
    photo = first.json()
    assert photo["id"].startswith("fp-")
    assert photo["content_hash"] == PHOTO["content_hash"]
    assert photo["storage_key"] == PHOTO["storage_key"]
    assert "provenance" not in photo  # stored, not echoed

    again = owner.post(f"/api/field-observations/{obs_id}/photos", json=PHOTO)
    assert again.status_code == 201
    assert again.json()["id"] == photo["id"]

    photos = owner.get(f"/api/field-observations/{obs_id}/photos").json()
    assert [p["id"] for p in photos] == [photo["id"]]
    assert owner.get(f"/api/field-observations/{obs_id}").json()["photo_count"] == 1


@pytest.mark.parametrize(
    "bad_photo",
    [
        {**PHOTO, "content_hash": "not-a-sha256"},
        {**PHOTO, "storage_key": "https://cdn.example.org/photo.jpg"},
        {**PHOTO, "photographer_subject": "someone@example.org"},
        {**PHOTO, "provenance": {"exif": {"gps": {"lat": 1.0, "lon": 2.0}}}},
    ],
)
def test_photo_attach_rejects_bad_provenance(owner, bad_photo):
    obs_id = owner.post("/api/field-observations", json=SAMPLE).json()["id"]
    assert owner.post(f"/api/field-observations/{obs_id}/photos", json=bad_photo).status_code == 422
    assert owner.get(f"/api/field-observations/{obs_id}").json()["photo_count"] == 0


# -- durability ---------------------------------------------------------------------------


def test_records_survive_a_fresh_service_over_the_same_store(owner):
    obs_id = owner.post("/api/field-observations", json=SAMPLE).json()["id"]
    owner.post(f"/api/field-observations/{obs_id}/photos", json=PHOTO)
    fresh = observation_service.FieldObservationService(observation_service.get_store())
    loaded = fresh.get(obs_id)
    assert loaded.id == obs_id
    assert loaded.photo_count == 1
    assert fresh.list_for(OWNER_AUTH["actor"]).total == 1


def test_main_app_serves_journey_5_and_journey_6_under_one_prefix():
    pytest.importorskip("psycopg", reason="app.main imports the full router set")
    from app.main import app as main_app

    paths = {route.path for route in main_app.routes}
    assert "/api/field-observations" in paths
    assert "/api/field-observations/{observation_id}" in paths
    assert "/api/field-observations/{observation_id}/photos" in paths
    assert "/api/field-observations/{observation_id}/curation" in paths
    assert "/api/field-observations/{observation_id}/hypotheses" in paths
