"""Field Journal originals archived to the owner's Google Drive (drive.file scope).

Every Drive interaction goes through a fake gateway that behaves like the
``drive.file`` scope: it only ever returns items this app created. Pre-existing
owner items (a Google Form and its response folder) sit in the fake Drive to
prove the archive never reads, writes or parents anything it did not create.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.field_observation import drive_archive
from app.field_observation import routes as observation_routes
from app.field_observation import service as observation_service
from app.field_observation.drive_archive import (
    DRIVE_FILE_SCOPE,
    FOLDER_MIME,
    ArchiveConfigError,
    DriveMediaArchive,
    GoogleDriveArchiveGateway,
    archive_filename,
    load_authorized_user_info,
)
from app.field_observation.routes import router
from app.security import verify_owner_or_api_key

OWNER_AUTH = {"actor": "owner@example.test", "auth_type": "owner_session"}
MEMBER_AUTH = {"actor": "backend_api_key", "auth_type": "api_key"}
ORIGINAL = b"\xff\xd8\xff\xe0field-journal-original-bytes"
SHA = hashlib.sha256(ORIGINAL).hexdigest()

# Built at runtime so no precise coordinate literal sits in this tracked file.
LAT_TEXT = f"{-12}.{3456}"
LON_TEXT = f"{-45}.{6789}"
COORDINATE_LIKE = re.compile(r"[-+]?\d{1,3}[.,]\d{3,}")

OBSERVATION = {
    "observed_at": "2026-10-03T14:20:00Z",
    "note": "Single flowering plant on mossy branch.",
    "locality_visibility": "private",
    "client_draft_id": "ipad-draft-archive-1",
}

FOREIGN_FORM_ID = "owner-google-form"
FOREIGN_RESPONSES_ID = "owner-form-responses-folder"


class FakeDrive:
    """drive.file semantics: only items created through this gateway are visible."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {
            FOREIGN_FORM_ID: {
                "id": FOREIGN_FORM_ID,
                "name": "Field Journal Form",
                "mimeType": "application/vnd.google-apps.form",
                "appProperties": {},
                "parents": ["root"],
                "app_created": False,
            },
            FOREIGN_RESPONSES_ID: {
                "id": FOREIGN_RESPONSES_ID,
                "name": "Field Journal Form (File responses)",
                "mimeType": FOLDER_MIME,
                "appProperties": {},
                "parents": ["root"],
                "app_created": False,
            },
        }
        self.data: dict[str, bytes] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.upload_error: BaseException | None = None
        self.corrupt_reported_md5 = False
        self.corrupt_download = False
        self.upload_delay = 0.0
        self.download_error: BaseException | None = None
        self._n = 0
        self._lock = threading.Lock()

    def _new_id(self, prefix: str) -> str:
        with self._lock:
            self._n += 1
            return f"{prefix}-{self._n}"

    def find(self, *, app_properties, parent_id, folders_only):
        self.calls.append(("find", {"app_properties": dict(app_properties), "parent_id": parent_id}))
        found = []
        for item in self.items.values():
            if not item["app_created"]:
                continue
            if (item["mimeType"] == FOLDER_MIME) != folders_only:
                continue
            if parent_id is not None and parent_id not in item["parents"]:
                continue
            if all(item["appProperties"].get(k) == v for k, v in app_properties.items()):
                found.append({k: v for k, v in item.items() if k != "app_created"})
        return found

    def create_folder(self, *, name, parent_id, app_properties):
        self.calls.append(("create_folder", {"name": name, "parent_id": parent_id, "app_properties": dict(app_properties)}))
        folder_id = self._new_id("folder")
        self.items[folder_id] = {
            "id": folder_id,
            "name": name,
            "mimeType": FOLDER_MIME,
            "appProperties": dict(app_properties),
            "parents": [parent_id or "root"],
            "createdTime": f"2026-10-17T00:00:{self._n:02d}Z",
            "app_created": True,
        }
        return {"id": folder_id}

    def upload(self, *, name, parent_id, data, mime_type, app_properties):
        self.calls.append(
            ("upload", {"name": name, "parent_id": parent_id, "mime_type": mime_type, "app_properties": dict(app_properties)})
        )
        if self.upload_delay:
            time.sleep(self.upload_delay)
        if self.upload_error is not None:
            raise self.upload_error
        file_id = self._new_id("file")
        md5 = hashlib.md5(data).hexdigest()
        if self.corrupt_reported_md5:
            md5 = "0" * 32
        self.items[file_id] = {
            "id": file_id,
            "name": name,
            "mimeType": mime_type,
            "appProperties": dict(app_properties),
            "parents": [parent_id],
            "md5Checksum": md5,
            "size": str(len(data)),
            "app_created": True,
        }
        self.data[file_id] = bytes(data)
        return {k: v for k, v in self.items[file_id].items() if k != "app_created"}

    def download(self, file_id):
        self.calls.append(("download", {"file_id": file_id}))
        if self.download_error is not None:
            raise self.download_error
        if file_id not in self.data:
            raise RuntimeError("not found")
        payload = self.data[file_id]
        return payload[:-1] + b"X" if self.corrupt_download else payload

    def uploads(self) -> list[dict[str, Any]]:
        return [args for name, args in self.calls if name == "upload"]


@pytest.fixture()
def fake_drive(tmp_path, monkeypatch):
    observation_service.configure_store(observation_service.memory_store())
    monkeypatch.setenv("FIELD_MEDIA_STORAGE_DIR", str(tmp_path / "field-media"))
    monkeypatch.delenv("FIELD_MEDIA_STORAGE_DURABLE", raising=False)
    monkeypatch.delenv("FIELD_MEDIA_DRIVE_CREDENTIALS_JSON", raising=False)
    drive = FakeDrive()
    drive_archive.configure_archive(DriveMediaArchive(drive, folder_name="Test Archive", timeout_seconds=5))
    yield drive
    drive_archive.configure_archive()
    observation_service.configure_store(None)


def _client(auth: dict[str, Any] = OWNER_AUTH) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: dict(auth)
    return TestClient(app)


@pytest.fixture()
def owner() -> TestClient:
    return _client()


def _observation(client: TestClient) -> str:
    resp = client.post("/api/field-observations", json=OBSERVATION)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


def _upload(client: TestClient, observation_id: str, data: bytes = ORIGINAL, filename: str = "IMG_0412.JPG",
            client_media_id: str = "local-media-1"):
    return client.post(
        f"/api/field-observations/{observation_id}/media",
        files={"file": (filename, data, "image/jpeg")},
        data={"media_kind": "photo", "client_media_id": client_media_id},
    )


def _local_path(tmp_path, sha: str = SHA):
    return tmp_path / "field-media" / "sha256" / sha[:2] / sha


def test_verified_drive_copy_makes_the_upload_durable(owner, fake_drive):
    observation_id = _observation(owner)
    resp = _upload(owner, observation_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["durability"] == "durable"
    assert body["archive"]["provider"] == "google_drive"
    assert body["archive"]["state"] == "verified"
    assert body["archive"]["drive_file_id"].startswith("file-")
    assert body["archive"]["error_code"] is None

    (upload,) = fake_drive.uploads()
    assert upload["app_properties"] == {
        "oc_archive": "field_journal_original",
        "oc_observation_id": observation_id,
        "oc_sha256": SHA,
        "oc_client_media_id": "local-media-1",
    }
    assert upload["name"] == f"{SHA[:16]}.jpg"

    record = observation_service.FieldObservationService(observation_service.get_store()).photo_record_by_hash(
        observation_id, SHA
    )
    receipt = record["provenance"]["archive"]
    assert receipt["state"] == "verified"
    assert receipt["md5"] == hashlib.md5(ORIGINAL).hexdigest()
    assert receipt["size"] == len(ORIGINAL)
    assert receipt["drive_folder_id"] and receipt["verified_at"]


def test_md5_mismatch_stays_pending_and_not_durable(owner, fake_drive):
    fake_drive.corrupt_reported_md5 = True
    observation_id = _observation(owner)
    resp = _upload(owner, observation_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["durability"] == "not_guaranteed"
    assert body["archive"]["state"] == "pending"
    assert body["archive"]["error_code"] == "drive_verification_failed"
    assert body["archive"]["drive_file_id"] is None


def test_drive_error_never_fails_the_upload(owner, fake_drive, tmp_path):
    fake_drive.upload_error = RuntimeError("HttpError 500 with secret-ish detail")
    observation_id = _observation(owner)
    resp = _upload(owner, observation_id)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["archive"] == {
        "provider": "google_drive",
        "state": "pending",
        "drive_file_id": None,
        "verified_at": None,
        "error_code": "drive_unavailable",
    }
    assert body["durability"] == "not_guaranteed"
    assert "secret-ish" not in resp.text
    assert _local_path(tmp_path).read_bytes() == ORIGINAL


def test_declared_local_durability_still_applies_when_drive_is_pending(owner, fake_drive, monkeypatch):
    fake_drive.upload_error = RuntimeError("down")
    monkeypatch.setenv("FIELD_MEDIA_STORAGE_DURABLE", "true")
    body = _upload(owner, _observation(owner)).json()
    assert body["durability"] == "durable"
    assert body["archive"]["state"] == "pending"


def test_reupload_retries_a_pending_archive_and_then_is_a_no_op(owner, fake_drive):
    fake_drive.upload_error = RuntimeError("down")
    observation_id = _observation(owner)
    assert _upload(owner, observation_id).json()["archive"]["state"] == "pending"

    fake_drive.upload_error = None
    retried = _upload(owner, observation_id).json()
    assert retried["archive"]["state"] == "verified"
    assert retried["durability"] == "durable"
    uploads_after_verify = len(fake_drive.uploads())

    again = _upload(owner, observation_id).json()
    assert again["archive"] == retried["archive"]
    assert len(fake_drive.uploads()) == uploads_after_verify


def test_idempotent_archive_reuses_an_existing_drive_file(fake_drive):
    """A copy that reached Drive after a timeout is found by oc_sha256, not uploaded twice."""
    archive = drive_archive.get_field_media_archive().archive
    assert archive is not None
    first = archive.archive(observation_id="fo-abc", data=ORIGINAL, sha256=SHA,
                            display_filename="IMG_0412.JPG", mime_type="image/jpeg")
    second = archive.archive(observation_id="fo-abc", data=ORIGINAL, sha256=SHA,
                             display_filename="IMG_0412.JPG", mime_type="image/jpeg")
    assert second.drive_file_id == first.drive_file_id
    assert second.reused_existing is True
    assert len(fake_drive.uploads()) == 1
    folders = [c for c in fake_drive.calls if c[0] == "create_folder"]
    assert len(folders) == 2  # one root, one observation subfolder; both reused the second time


def test_timeout_is_bounded_and_the_late_copy_is_reused_on_retry(owner, fake_drive):
    drive_archive.configure_archive(DriveMediaArchive(fake_drive, folder_name="Test Archive", timeout_seconds=0.2))
    fake_drive.upload_delay = 1.0
    observation_id = _observation(owner)
    started = time.monotonic()
    body = _upload(owner, observation_id).json()
    assert time.monotonic() - started < 0.9
    assert body["archive"]["state"] == "pending"
    assert body["archive"]["error_code"] == "drive_timeout"
    assert body["durability"] == "not_guaranteed"

    time.sleep(1.2)  # the slow upload finishes in the background
    fake_drive.upload_delay = 0.0
    retried = _upload(owner, observation_id).json()
    assert retried["archive"]["state"] == "verified"
    assert len(fake_drive.uploads()) == 1


def test_root_folder_is_found_by_marker_not_by_name(fake_drive):
    archive = drive_archive.get_field_media_archive().archive
    archive.archive(observation_id="fo-1", data=ORIGINAL, sha256=SHA, display_filename="a.jpg", mime_type="image/jpeg")
    # A new process with a renamed folder setting must reuse the same root folder.
    renamed = DriveMediaArchive(fake_drive, folder_name="Renamed Archive")
    receipt = renamed.archive(observation_id="fo-2", data=ORIGINAL, sha256=SHA, display_filename="a.jpg", mime_type="image/jpeg")
    roots = [i for i in fake_drive.items.values() if i["appProperties"].get("oc_archive") == "field_journal_media_root"]
    assert len(roots) == 1
    assert fake_drive.items[receipt.drive_folder_id]["parents"] == [roots[0]["id"]]
    # A same-named folder without the marker is never adopted.
    assert all(c[1]["app_properties"] for c in fake_drive.calls if c[0] == "find")


def test_retry_endpoint_archives_pending_media_in_a_bounded_batch(owner, fake_drive):
    fake_drive.upload_error = RuntimeError("down")
    observation_id = _observation(owner)
    hashes = []
    for index in range(3):
        data = ORIGINAL + bytes([index])
        hashes.append(hashlib.sha256(data).hexdigest())
        assert _upload(owner, observation_id, data=data).json()["archive"]["state"] == "pending"

    fake_drive.upload_error = None
    first = owner.post("/api/field-observations/archive/retry", params={"limit": 2})
    assert first.status_code == 200, first.text
    assert first.json() == {
        "provider": "google_drive",
        "attempted": 2,
        "verified": 2,
        "still_pending": 0,
        "skipped_local_bytes_missing": 0,
        "remaining": 1,
        "deadline_reached": False,
        "pending_after": 1,
    }
    second = owner.post("/api/field-observations/archive/retry").json()
    assert second["attempted"] == 1 and second["verified"] == 1 and second["remaining"] == 0
    assert second["pending_after"] == 0
    assert owner.post("/api/field-observations/archive/retry", params={"limit": 11}).status_code == 422

    status = owner.get("/api/field-observations/archive/status")
    assert status.status_code == 200, status.text
    assert status.json()["counts"] == {"verified": 3, "pending": 0, "not_configured": 0, "untracked": 0}


def test_retry_skips_media_whose_local_bytes_are_gone(owner, fake_drive, tmp_path):
    fake_drive.upload_error = RuntimeError("down")
    observation_id = _observation(owner)
    _upload(owner, observation_id)
    _local_path(tmp_path).unlink()
    fake_drive.upload_error = None
    body = owner.post("/api/field-observations/archive/retry").json()
    assert body["attempted"] == 0 and body["skipped_local_bytes_missing"] == 1
    status = owner.get("/api/field-observations/archive/status").json()
    assert status["counts"]["pending"] == 1
    assert status["error_codes"] == {"local_bytes_missing": 1}
    assert status["unarchived_without_local_bytes"] == 1


def test_status_holds_counts_only_and_probe_is_read_only(owner, fake_drive):
    observation_id = _observation(owner)
    _upload(owner, observation_id)
    calls_before = len(fake_drive.calls)
    resp = owner.get("/api/field-observations/archive/status", params={"probe": "true"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["probe"] == {"ok": True, "archive_folder_present": True}
    assert observation_id not in resp.text and SHA not in resp.text
    assert "owner@example.test" not in resp.text and "IMG_0412" not in resp.text
    assert [c[0] for c in fake_drive.calls[calls_before:]] == ["find"]


def test_archive_management_is_not_an_observer_action(fake_drive):
    member = _client(MEMBER_AUTH)
    headers = {"X-Auth-Subject": "member-opaque-1"}
    assert member.get("/api/field-observations/archive/status", headers=headers).status_code == 403
    assert member.post("/api/field-observations/archive/retry", headers=headers).status_code == 403
    service_identity = _client(MEMBER_AUTH)
    assert service_identity.get("/api/field-observations/archive/status").status_code == 200


def test_not_configured_reports_honestly(owner, fake_drive):
    drive_archive.configure_archive(None)
    body = _upload(owner, _observation(owner)).json()
    assert body["durability"] == "not_guaranteed"
    assert body["archive"]["state"] == "not_configured"
    assert body["archive"]["error_code"] == "drive_not_configured"
    retry = owner.post("/api/field-observations/archive/retry")
    assert retry.status_code == 409
    assert retry.json()["detail"]["error_code"] == "drive_not_configured"
    status = owner.get("/api/field-observations/archive/status").json()
    assert status["configured"] is False
    assert status["counts"]["not_configured"] == 1


def test_readback_falls_back_to_the_verified_drive_copy(owner, fake_drive, tmp_path):
    observation_id = _observation(owner)
    assert _upload(owner, observation_id).json()["archive"]["state"] == "verified"
    _local_path(tmp_path).unlink()

    url = f"/api/field-observations/{observation_id}/media/{SHA}/original"
    resp = owner.get(url)
    assert resp.status_code == 200, resp.text
    assert resp.content == ORIGINAL
    assert resp.headers["x-field-media-source"] == "google_drive_archive"
    assert resp.headers["cache-control"].startswith("private, no-store")
    # The verified copy rehydrates the local cache.
    assert _local_path(tmp_path).read_bytes() == ORIGINAL
    assert owner.get(url).headers["x-field-media-source"] == "server"


def test_readback_refuses_a_drive_copy_that_fails_md5(owner, fake_drive, tmp_path):
    observation_id = _observation(owner)
    _upload(owner, observation_id)
    _local_path(tmp_path).unlink()
    fake_drive.corrupt_download = True
    resp = owner.get(f"/api/field-observations/{observation_id}/media/{SHA}/original")
    assert resp.status_code == 502
    assert not _local_path(tmp_path).exists()


def test_readback_drive_outage_is_503_and_unarchived_loss_is_still_410(owner, fake_drive, tmp_path):
    observation_id = _observation(owner)
    _upload(owner, observation_id)
    _local_path(tmp_path).unlink()
    fake_drive.download_error = RuntimeError("down")
    assert owner.get(f"/api/field-observations/{observation_id}/media/{SHA}/original").status_code == 503

    fake_drive.upload_error = RuntimeError("down")
    other = ORIGINAL + b"-unarchived"
    other_sha = hashlib.sha256(other).hexdigest()
    _upload(owner, observation_id, data=other)
    _local_path(tmp_path, other_sha).unlink()
    assert owner.get(f"/api/field-observations/{observation_id}/media/{other_sha}/original").status_code == 410


def test_no_coordinates_or_locality_reach_drive_metadata(owner, fake_drive):
    observation_id = _observation(owner)
    resp = _upload(
        owner,
        observation_id,
        filename=f"orchid_{LAT_TEXT}_{LON_TEXT}.jpg",
        client_media_id=f"pt{LAT_TEXT}",
    )
    assert resp.status_code == 201, resp.text
    metadata = json.dumps(
        [args for name, args in fake_drive.calls if name in {"upload", "create_folder"}]
    )
    assert not COORDINATE_LIKE.search(metadata)
    assert LAT_TEXT not in metadata and LON_TEXT not in metadata
    for forbidden in ("lat", "lon", "locality", "coordinates", "habitat", "note", "owner@example.test"):
        assert forbidden not in metadata.lower().replace("oc_archive", "")
    (upload,) = fake_drive.uploads()
    assert "oc_client_media_id" not in upload["app_properties"]
    folder_names = [args["name"] for name, args in fake_drive.calls if name == "create_folder"]
    assert folder_names == ["Test Archive", observation_id]


def test_nothing_touches_items_the_app_did_not_create(owner, fake_drive):
    foreign_before = {k: dict(v) for k, v in fake_drive.items.items() if not v["app_created"]}
    observation_id = _observation(owner)
    _upload(owner, observation_id)
    owner.post("/api/field-observations/archive/retry")
    owner.get("/api/field-observations/archive/status", params={"probe": "true"})

    app_ids = {k for k, v in fake_drive.items.items() if v["app_created"]}
    for name, args in fake_drive.calls:
        assert args.get("parent_id") in app_ids | {None}, (name, args)
        assert args.get("file_id") in app_ids | {None}, (name, args)
        if name == "find":
            assert args["app_properties"].get("oc_archive"), "every lookup is scoped by the app marker"
    assert {k: v for k, v in fake_drive.items.items() if not v["app_created"]} == foreign_before
    serialized = json.dumps(fake_drive.calls)
    assert FOREIGN_FORM_ID not in serialized and FOREIGN_RESPONSES_ID not in serialized


# -- credentials -----------------------------------------------------------------------------

AUTHORIZED_USER = {
    "type": "authorized_user",
    "client_id": "test-client-id.apps.googleusercontent.com",
    "client_secret": "test-client-secret-not-real",
    "refresh_token": "test-refresh-token-not-real",
}


def test_service_account_credentials_are_rejected_with_the_quota_reason():
    with pytest.raises(ArchiveConfigError) as excinfo:
        load_authorized_user_info(json.dumps({"type": "service_account", "private_key": "TEST-NOT-A-KEY"}))
    message = str(excinfo.value)
    assert "storage quota" in message and "authorized_user" in message
    assert "TEST-NOT-A-KEY" not in message


@pytest.mark.parametrize(
    "raw",
    ["not json", "[]", json.dumps({**AUTHORIZED_USER, "refresh_token": ""}), json.dumps({**AUTHORIZED_USER, "type": "external_account"})],
)
def test_unusable_credentials_are_rejected_without_echoing_values(raw):
    with pytest.raises(ArchiveConfigError) as excinfo:
        load_authorized_user_info(raw)
    assert "test-client-secret-not-real" not in str(excinfo.value)


def test_service_account_env_leaves_uploads_pending_not_durable(owner, fake_drive, monkeypatch):
    drive_archive.configure_archive()  # back to the environment
    monkeypatch.setenv(
        "FIELD_MEDIA_DRIVE_CREDENTIALS_JSON", json.dumps({"type": "service_account", "private_key": "TEST-NOT-A-KEY"})
    )
    resp = _upload(owner, _observation(owner))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["durability"] == "not_guaranteed"
    assert body["archive"]["state"] == "pending"
    assert body["archive"]["error_code"] == "drive_credentials_invalid"
    status = owner.get("/api/field-observations/archive/status").json()
    assert status["configured"] is False and status["configuration_error"] == "drive_credentials_invalid"
    assert "TEST-NOT-A-KEY" not in json.dumps(status)


def test_google_gateway_uses_only_the_drive_file_scope():
    gateway = GoogleDriveArchiveGateway.from_authorized_user_info(
        load_authorized_user_info(json.dumps(AUTHORIZED_USER)), timeout_seconds=5
    )
    credentials = gateway.service._http.credentials
    assert list(credentials.scopes) == [DRIVE_FILE_SCOPE]


class _Request:
    def __init__(self, result):
        self.result = result

    def execute(self, num_retries=0):
        return self.result


class _Files:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return _Request({"files": []})

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return _Request({"id": "x", "md5Checksum": "m", "size": "1"})


class _Service:
    """Has files() only; a permissions()/sharing call would raise AttributeError."""

    def __init__(self):
        self._files = _Files()

    def files(self):
        return self._files


def test_google_gateway_queries_are_marker_scoped_and_never_share():
    service = _Service()
    gateway = GoogleDriveArchiveGateway(service)
    gateway.find(app_properties={"oc_archive": "field_journal_media_root"}, parent_id=None, folders_only=True)
    gateway.find(app_properties={"oc_archive": "field_journal_original", "oc_sha256": "ab'c"}, parent_id="folder-1",
                 folders_only=False)
    gateway.create_folder(name="Root", parent_id=None, app_properties={"oc_archive": "field_journal_media_root"})
    gateway.upload(name="a.jpg", parent_id="folder-1", data=b"abc", mime_type="image/jpeg",
                   app_properties={"oc_archive": "field_journal_original"})
    lists = [kwargs for name, kwargs in service._files.calls if name == "list"]
    assert all("appProperties has { key='oc_archive'" in kw["q"] for kw in lists)
    assert all(kw["spaces"] == "drive" and "trashed = false" in kw["q"] for kw in lists)
    assert "value='ab\\'c'" in lists[1]["q"] and "'folder-1' in parents" in lists[1]["q"]
    creates = [kwargs for name, kwargs in service._files.calls if name == "create"]
    assert creates[0]["body"]["mimeType"] == FOLDER_MIME and "parents" not in creates[0]["body"]
    media = creates[1]["media_body"]
    assert media.resumable() is True
    for _, kwargs in service._files.calls:
        assert "permissions" not in json.dumps(kwargs.get("body", {}))
    with pytest.raises(ValueError):
        gateway.build_query(app_properties={}, parent_id="folder-1", folders_only=False)


# -- review fixes: filename privacy, no downgrade, credential hygiene, retry deadline ------------


def test_drive_file_name_never_carries_the_users_filename(owner, fake_drive):
    observation_id = _observation(owner)
    resp = _upload(owner, observation_id, filename="Cerro_X_trailhead.jpg")
    assert resp.status_code == 201, resp.text
    drive_metadata = json.dumps([args for name, args in fake_drive.calls if name in {"upload", "create_folder"}])
    assert "Cerro" not in drive_metadata and "trailhead" not in drive_metadata
    (upload,) = fake_drive.uploads()
    assert upload["name"] == f"{SHA[:16]}.jpg"
    record = observation_service.FieldObservationService(observation_service.get_store()).photo_record_by_hash(
        observation_id, SHA
    )
    assert record["provenance"]["original_filename"] == "Cerro_X_trailhead.jpg"


@pytest.mark.parametrize(
    ("display", "mime", "expected_ext"),
    [
        ("IMG_1.HEIC", "image/heic", ".heic"),
        ("clip.MOV", "video/quicktime", ".mov"),
        ("Cerro_X.php", "image/png", ".png"),
        ("no-extension", "video/mp4", ".mp4"),
        ("weird.exe", "application/x-unknown", ".bin"),
        (f"pt{LAT_TEXT}", "", ".bin"),
    ],
)
def test_archive_filename_is_hash_plus_allowlisted_extension(display, mime, expected_ext):
    assert archive_filename(display, SHA, mime) == f"{SHA[:16]}{expected_ext}"


def test_verified_archive_state_is_never_downgraded(owner, fake_drive):
    observation_id = _observation(owner)
    verified = _upload(owner, observation_id).json()["archive"]
    service = observation_service.FieldObservationService(observation_service.get_store())
    stale = {"provider": "google_drive", "state": "pending", "error_code": "drive_timeout"}
    row = service.set_media_archive(observation_id, SHA, stale)
    assert row["provenance"]["archive"]["state"] == "verified"
    assert service.photo_record_by_hash(observation_id, SHA)["provenance"]["archive"]["drive_file_id"] == verified[
        "drive_file_id"
    ]


def test_stale_timed_out_attempt_reports_the_verified_state(owner, fake_drive):
    """A request whose attempt timed out after another request verified the copy reports verified."""
    observation_id = _observation(owner)
    _upload(owner, observation_id)
    service = observation_service.FieldObservationService(observation_service.get_store())
    record = service.photo_record_by_hash(observation_id, SHA)
    stale_record = {**record, "provenance": {**record["provenance"], "archive": {"state": "pending"}}}
    failing_drive = FakeDrive()
    failing_drive.upload_error = RuntimeError("down")
    config = drive_archive.ArchiveConfig(DriveMediaArchive(failing_drive, folder_name="Other", timeout_seconds=5), None)
    state = observation_routes.archive_original_sync(service, config, observation_id, stale_record, ORIGINAL)
    assert state["state"] == "verified"


def test_credential_json_drops_token_expiry_and_scopes():
    info = load_authorized_user_info(
        json.dumps(
            {
                **AUTHORIZED_USER,
                "token": "stale-access-token",
                "expiry": "2030-01-01T00:00:00Z",
                "scopes": ["https://www.googleapis.com/auth/drive"],
                "universe_domain": "googleapis.com",
            }
        )
    )
    assert info == {**AUTHORIZED_USER}
    gateway = GoogleDriveArchiveGateway.from_authorized_user_info(info, timeout_seconds=5)
    credentials = gateway.service._http.credentials
    assert credentials.token is None
    assert list(credentials.scopes) == [DRIVE_FILE_SCOPE]


def test_retry_request_stops_at_its_deadline(owner, fake_drive, monkeypatch):
    fake_drive.upload_error = RuntimeError("down")
    observation_id = _observation(owner)
    for index in range(3):
        _upload(owner, observation_id, data=ORIGINAL + bytes([index]))
    fake_drive.upload_error = None
    fake_drive.upload_delay = 0.6
    monkeypatch.setattr(observation_routes, "ARCHIVE_RETRY_DEADLINE_SECONDS", 0.3)
    started = time.monotonic()
    body = owner.post("/api/field-observations/archive/retry").json()
    assert time.monotonic() - started < 0.6
    assert body["attempted"] == 1 and body["still_pending"] == 1
    assert body["deadline_reached"] is True and body["remaining"] == 2
    assert body["pending_after"] == 3
    time.sleep(0.5)  # let the background upload finish before teardown
