"""Producer/consumer contract: the Field Journal iPad client against the real app.

Replays the exact request shapes the frontend sends (orchid-continuum-frontend
``src/lib/fieldJournal.ts::toFieldObservationUploadPayload`` and
``src/lib/fieldJournalSync.ts``, branch ``field-journal/offline-mvp``) through
``app.main.app`` -- real owner-session auth, real CORS middleware -- rather
than a router with the auth dependency overridden.

What the client relies on:

* ``POST /api/field-observations`` returns a string ``id``; a retry with the
  same ``client_draft_id`` returns the same ``id``.
* ``POST /api/field-observations/{id}/media`` (multipart ``file``,
  ``captured_at``, ``media_kind``, ``client_media_id``) returns ``id``,
  ``storage_key`` and ``content_hash`` equal to the SHA-256 of the bytes it
  sent, and is idempotent for the same bytes.
* Auth is the owner bearer token from ``/api/mission-control/owner/session-token``.
* Private capture GPS and locality notes never travel in, or are stored from,
  this payload.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app.field_observation import service as observation_service
from app.main import app

PILOT_ORIGIN = "https://orchid-continuum-frontend-ny5w77l3b-jsp1440-2266s-projects.vercel.app"
LOCAL_DRAFT_ID = "6f1c0a52-8d4b-4c4e-9a59-2f3c1e7d9b10"
LOCAL_MEDIA_ID = "0b8f8c2e-3c1d-4b7a-8f0e-5a6d7c8b9a01"

# Exactly what toFieldObservationUploadPayload emits for a fresh, unresolved
# entry: every key present, optional text as null, media as metadata only.
FRONTEND_PAYLOAD = {
    "observed_at": "2026-10-17T17:42:10.123Z",
    "device_captured_at": "2026-10-17T17:42:10.123Z",
    "note": "Epiphyte on a mossy trunk, two open flowers, photographed offline.",
    "taxon_hint": None,
    "epistemic_certainty": "POSSIBLE",
    "locality_visibility": "private",
    "habitat": "cloud forest edge",
    "substrate": None,
    "ecological_notes": None,
    "associated_organisms": [],
    "pollinator_observations": None,
    "mycorrhizal_observations": None,
    "phenology": "two open flowers",
    "media": [{"name": "IMG_0412.JPG", "size": 13, "type": "image/jpeg"}],
    "client_draft_id": LOCAL_DRAFT_ID,
}

# The device-only record the client keeps but must never send.
PRIVATE_LOCATION = {
    "latitude": 9.87654321,
    "longitude": -84.12345678,
    "accuracyM": 4.5,
    "elevationM": 1520.0,
    "capturedAt": "2026-10-17T17:42:09.000Z",
    "localityNotes": "behind the third switchback past the ranger hut",
}

ORIGINAL_BYTES = b"\xff\xd8\xff\xe0original"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FIELD_MEDIA_STORAGE_DURABLE", raising=False)
    monkeypatch.setenv("CALYX_OWNER_ACCESS_CODE", "owner-code")
    monkeypatch.setenv("CALYX_OWNER_SESSION_SECRET", "owner-session-secret")
    monkeypatch.setenv("CORS_ALLOW_ORIGIN", PILOT_ORIGIN)
    monkeypatch.setenv("FIELD_MEDIA_STORAGE_DIR", str(tmp_path / "field-media"))
    store = observation_service.memory_store()
    observation_service.configure_store(store)
    client = TestClient(app, raise_server_exceptions=False)
    client.store = store  # type: ignore[attr-defined]
    yield client
    observation_service.configure_store(None)


def _owner_bearer(client: TestClient) -> dict[str, str]:
    login = client.post(
        "/api/mission-control/owner/session-token",
        json={"access_code": "owner-code"},
        headers={"Origin": PILOT_ORIGIN},
    )
    assert login.status_code == 200, login.text
    token = login.json()["token"]
    # The frontend transport sends the bearer and credentials; drop the cookie
    # so this proves the bearer path Safari falls back to on cross-site POSTs.
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}", "Origin": PILOT_ORIGIN, "Accept": "application/json"}


def _upload(client: TestClient, observation_id: str, headers: dict[str, str], data: bytes = ORIGINAL_BYTES):
    return client.post(
        f"/api/field-observations/{observation_id}/media",
        headers=headers,
        files={"file": ("IMG_0412.JPG", data, "image/jpeg")},
        data={
            "captured_at": "2026-10-17T17:42:10.123Z",
            "media_kind": "photo",
            "client_media_id": LOCAL_MEDIA_ID,
        },
    )


def _all_store_keys(value) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key).lower())
            keys |= _all_store_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _all_store_keys(item)
    return keys


def test_frontend_sync_round_trip_with_owner_bearer(client):
    headers = _owner_bearer(client)

    created = client.post("/api/field-observations", headers=headers, json=FRONTEND_PAYLOAD)
    assert created.status_code == 201, created.text
    assert created.headers["content-type"].startswith("application/json")
    assert created.headers["access-control-allow-origin"] == PILOT_ORIGIN
    assert created.headers["access-control-allow-credentials"] == "true"
    observation_id = created.json()["id"]
    assert isinstance(observation_id, str) and observation_id.startswith("fo-")
    assert created.json()["identification_status"] == "unresolved"

    retried = client.post("/api/field-observations", headers=headers, json=FRONTEND_PAYLOAD)
    assert retried.status_code == 200, retried.text
    assert retried.json()["id"] == observation_id

    uploaded = _upload(client, observation_id, headers)
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.headers["access-control-allow-origin"] == PILOT_ORIGIN
    receipt = uploaded.json()
    assert receipt["content_hash"] == hashlib.sha256(ORIGINAL_BYTES).hexdigest()
    assert isinstance(receipt["id"], str) and receipt["id"]
    assert isinstance(receipt["storage_key"], str) and receipt["storage_key"]
    assert receipt["durability"] == "not_guaranteed"

    again = _upload(client, observation_id, headers)
    assert again.status_code in (200, 201), again.text
    assert {k: again.json()[k] for k in ("id", "storage_key", "content_hash")} == {
        k: receipt[k] for k in ("id", "storage_key", "content_hash")
    }
    listed = client.get(f"/api/field-observations/{observation_id}/photos", headers=headers)
    assert listed.status_code == 200 and len(listed.json()) == 1

    original = client.get(
        f"/api/field-observations/{observation_id}/media/{receipt['content_hash']}/original",
        headers=headers,
    )
    assert original.status_code == 200 and original.content == ORIGINAL_BYTES


def test_durability_is_claimed_only_when_operator_declares_it(client, monkeypatch):
    headers = _owner_bearer(client)
    observation_id = client.post("/api/field-observations", headers=headers, json=FRONTEND_PAYLOAD).json()["id"]
    monkeypatch.setenv("FIELD_MEDIA_STORAGE_DURABLE", "yes-ish")
    assert _upload(client, observation_id, headers).json()["durability"] == "not_guaranteed"
    monkeypatch.setenv("FIELD_MEDIA_STORAGE_DURABLE", "true")
    assert _upload(client, observation_id, headers).json()["durability"] == "durable"


def test_media_preflight_allows_pilot_origin_with_authorization(client):
    for path, content_type in (
        ("/api/field-observations", "content-type"),
        ("/api/field-observations/fo-abc/media", ""),
    ):
        requested = ",".join(filter(None, ("authorization", content_type)))
        resp = client.options(
            path,
            headers={
                "Origin": PILOT_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": requested,
            },
        )
        assert resp.status_code == 200
        assert resp.headers["access-control-allow-origin"] == PILOT_ORIGIN
        assert resp.headers["access-control-allow-credentials"] == "true"
        allowed = resp.headers["access-control-allow-headers"].lower()
        assert "authorization" in allowed and "content-type" in allowed
        assert "POST" in resp.headers["access-control-allow-methods"]


def test_unlisted_vercel_origin_gets_no_credentialed_cors(client, monkeypatch):
    """A Vercel preview origin is allowed only through CORS_ALLOW_ORIGIN, never by pattern."""
    monkeypatch.delenv("CORS_ALLOW_ORIGIN", raising=False)
    resp = client.options(
        "/api/field-observations",
        headers={"Origin": PILOT_ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in resp.headers


def test_unauthenticated_sync_fails_closed_as_json(client):
    resp = client.post(
        "/api/field-observations",
        headers={"Origin": PILOT_ORIGIN, "Accept": "application/json"},
        json=FRONTEND_PAYLOAD,
    )
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize(
    "smuggled",
    [
        {"privateLocation": PRIVATE_LOCATION},
        {"latitude": PRIVATE_LOCATION["latitude"], "longitude": PRIVATE_LOCATION["longitude"]},
        {"locality_notes": PRIVATE_LOCATION["localityNotes"]},
        {"localityNotes": PRIVATE_LOCATION["localityNotes"]},
        {"media": [{"name": "a.jpg", "size": 1, "type": "image/jpeg", "gps": "9.87,-84.12"}]},
    ],
)
def test_private_capture_location_is_refused_not_stored(client, smuggled):
    headers = _owner_bearer(client)
    resp = client.post("/api/field-observations", headers=headers, json={**FRONTEND_PAYLOAD, **smuggled})
    assert resp.status_code == 422, resp.text
    assert client.store._records == {}


def test_stored_records_carry_no_coordinates_or_locality_notes(client):
    headers = _owner_bearer(client)
    observation_id = client.post("/api/field-observations", headers=headers, json=FRONTEND_PAYLOAD).json()["id"]
    _upload(client, observation_id, headers, data=b"\xff\xd8\xff\xe0exif-gps-may-live-here")

    dumped = json.dumps(list(client.store._records.values()), default=str)
    for secret in ("9.876", "-84.123", "third switchback", "ranger hut"):
        assert secret not in dumped
    keys = _all_store_keys(json.loads(dumped))
    for forbidden in ("latitude", "longitude", "lat", "lon", "lng", "gps", "locality", "locality_notes", "localitynotes"):
        assert forbidden not in keys

    # Originals are kept unmodified, and the record says so rather than
    # implying any EXIF location was stripped.
    photo = observation_service.FieldObservationService(client.store).photo_record_by_hash(
        observation_id, hashlib.sha256(b"\xff\xd8\xff\xe0exif-gps-may-live-here").hexdigest()
    )
    assert photo["provenance"]["embedded_metadata"] == "original_unmodified_may_include_device_location"
