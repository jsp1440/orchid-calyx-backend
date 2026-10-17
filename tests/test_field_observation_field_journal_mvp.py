"""Saturday Field Journal MVP additions to journey 5.

Covers the additive ecology/unresolved-identification contract and the original
media byte-preservation route without rewriting the existing journey-5 tests.
"""

from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.field_observation import service as observation_service
from app.field_observation.routes import router
from app.security import verify_owner_or_api_key

OWNER_AUTH = {"actor": "owner@example.test", "auth_type": "owner_session"}

BASE = {
    "observed_at": "2026-10-03T14:20:00Z",
    "device_captured_at": "2026-10-03T14:20:04Z",
    "note": "Single flowering plant on mossy branch; photo and short video captured offline.",
    "locality_visibility": "private",
    "habitat": "cloud forest edge",
    "substrate": "mossy branch",
    "ecological_notes": "Within 2 m of a flowering shrub; no bait used.",
    "associated_organisms": ["small bee", "moss"],
    "pollinator_observations": "bee approached but did not contact column",
    "mycorrhizal_observations": "not observed",
    "phenology": "one open flower",
    "client_draft_id": "ipad-local-uuid-1",
}


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    observation_service.configure_store(observation_service.memory_store())
    monkeypatch.setenv("FIELD_MEDIA_STORAGE_DIR", str(tmp_path / "field-media"))
    yield
    observation_service.configure_store(None)


@pytest.fixture()
def owner() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: dict(OWNER_AUTH)
    return TestClient(app)


def test_unresolved_observation_carries_ecology_without_coordinates(owner):
    resp = owner.post("/api/field-observations", json=BASE)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["identification_status"] == "unresolved"
    assert body["taxon_hint"] is None
    assert body["habitat"] == "cloud forest edge"
    assert body["substrate"] == "mossy branch"
    assert body["associated_organisms"] == ["small bee", "moss"]
    assert body["pollinator_observations"].startswith("bee approached")
    assert body["device_captured_at"].startswith("2026-10-03T14:20:04")
    assert "latitude" not in body
    assert "decimalLatitude" not in body


@pytest.mark.parametrize(
    "bad_payload",
    [
        {**BASE, "latitude": -13.1},
        {**BASE, "decimalLatitude": -13.1},
        {**BASE, "locality_notes": "behind the lodge"},
        {**BASE, "ecological_notes": {"nested": {"coordinates": [-13.1, -72.9]}}},
    ],
)
def test_mvp_payload_still_fails_closed_on_private_location_keys(owner, bad_payload):
    resp = owner.post("/api/field-observations", json=bad_payload)
    assert resp.status_code == 422
    assert owner.get("/api/field-observations").json()["total"] == 0


def test_original_photo_upload_is_byte_preserving_and_idempotent(owner):
    obs_id = owner.post("/api/field-observations", json=BASE).json()["id"]
    original = b"original-jpeg-bytes-not-recompressed"
    digest = hashlib.sha256(original).hexdigest()
    files = {"file": ("IMG_0001.jpg", original, "image/jpeg")}
    data = {"captured_at": "2026-10-03T14:20:04Z", "media_kind": "photo", "client_media_id": "media-1"}

    first = owner.post(f"/api/field-observations/{obs_id}/media", files=files, data=data)
    assert first.status_code == 201, first.text
    second = owner.post(f"/api/field-observations/{obs_id}/media", files=files, data=data)
    assert second.status_code == 201, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["content_hash"] == digest
    assert first.json()["media_kind"] == "photo"

    observation = owner.get(f"/api/field-observations/{obs_id}").json()
    assert observation["photo_count"] == 1
    download = owner.get(f"/api/field-observations/{obs_id}/media/{digest}/original")
    assert download.status_code == 200
    assert download.content == original
    assert download.headers["Cache-Control"].startswith("private")


def test_original_video_upload_is_accepted_as_video(owner):
    obs_id = owner.post("/api/field-observations", json=BASE).json()["id"]
    original = b"original-video-bytes"
    digest = hashlib.sha256(original).hexdigest()
    resp = owner.post(
        f"/api/field-observations/{obs_id}/media",
        files={"file": ("VID_0001.mp4", original, "video/mp4")},
        data={"media_kind": "video", "client_media_id": "video-1"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["media_kind"] == "video"
    assert resp.json()["content_hash"] == digest
    assert owner.get(f"/api/field-observations/{obs_id}/media/{digest}/original").content == original


def test_media_upload_rejects_non_media_and_oversized_files(owner, monkeypatch):
    obs_id = owner.post("/api/field-observations", json=BASE).json()["id"]
    assert owner.post(
        f"/api/field-observations/{obs_id}/media",
        files={"file": ("notes.txt", b"text", "text/plain")},
    ).status_code == 422
    monkeypatch.setenv("FIELD_MEDIA_MAX_BYTES", "3")
    assert owner.post(
        f"/api/field-observations/{obs_id}/media",
        files={"file": ("IMG.jpg", b"four", "image/jpeg")},
    ).status_code == 413
