"""Google Drive archive for Field Journal original media.

The owner's Drive is a personal Google account. Service accounts have no
storage quota in a personal My Drive, so the archive authenticates with OAuth
*authorized_user* credentials restricted to the ``drive.file`` scope: the app
can see and change only files it created itself. It creates its own archive
folder (found again by an ``appProperties`` marker, never by name alone) and a
subfolder per observation, and never reads, lists, moves or shares anything
else in the owner's Drive -- in particular not the Google Forms or their
response folders.

A copy counts as archived only after Drive reports an ``md5Checksum`` and
``size`` that equal the locally computed MD5 and byte length. Nothing here sets
sharing permissions: archived files stay private to the owner.

Drive metadata never carries coordinates or locality: folder names are the
opaque observation id, file names are the sanitized original filename with any
coordinate-like decimal removed, and ``appProperties`` hold only opaque ids and
the SHA-256 content hash.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, TypeVar

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_MIME = "application/vnd.google-apps.folder"
DEFAULT_FOLDER_NAME = "Orchid Continuum — Field Journal Media Archive"
DEFAULT_TIMEOUT_SECONDS = 60.0
MAX_TIMEOUT_SECONDS = 600.0
PROVIDER = "google_drive"

MARKER_KEY = "oc_archive"
MARKER_ROOT = "field_journal_media_root"
MARKER_OBSERVATION = "field_journal_observation"
MARKER_ORIGINAL = "field_journal_original"

#: Drive limits one appProperties entry to 124 bytes, key and value together.
_APP_PROPERTY_BYTES = 124
_COORDINATE_LIKE = re.compile(r"[-+]?\d{1,3}[.,]\d{3,}")

STATE_VERIFIED = "verified"
STATE_PENDING = "pending"
STATE_NOT_CONFIGURED = "not_configured"

ERROR_NOT_CONFIGURED = "drive_not_configured"
ERROR_CREDENTIALS_INVALID = "drive_credentials_invalid"
ERROR_TIMEOUT = "drive_timeout"
ERROR_VERIFICATION_FAILED = "drive_verification_failed"
ERROR_UNAVAILABLE = "drive_unavailable"
ERROR_LOCAL_BYTES_MISSING = "local_bytes_missing"

SERVICE_ACCOUNT_REJECTION = (
    "FIELD_MEDIA_DRIVE_CREDENTIALS_JSON holds a service_account credential. Google service "
    "accounts have no storage quota in a personal Google Drive (My Drive), so uploads would "
    "fail. Use OAuth authorized_user credentials (client_id, client_secret, refresh_token) "
    "issued for the owner's account with the drive.file scope; see "
    "docs/field-journal-drive-archive.md."
)


class ArchiveConfigError(RuntimeError):
    """The archive credentials or settings are unusable. The message holds no secret."""


class ArchiveError(RuntimeError):
    """An archive attempt failed; ``error_code`` is the only thing reported outward."""

    def __init__(self, error_code: str, message: str = "") -> None:
        super().__init__(message or error_code)
        self.error_code = error_code


class DriveArchiveGateway(Protocol):
    """The only Drive operations the archive performs. No permissions/sharing call exists."""

    def find(
        self, *, app_properties: Mapping[str, str], parent_id: str | None, folders_only: bool
    ) -> list[dict[str, Any]]: ...

    def create_folder(
        self, *, name: str, parent_id: str | None, app_properties: Mapping[str, str]
    ) -> dict[str, Any]: ...

    def upload(
        self,
        *,
        name: str,
        parent_id: str,
        data: bytes,
        mime_type: str,
        app_properties: Mapping[str, str],
    ) -> dict[str, Any]: ...

    def download(self, file_id: str) -> bytes: ...


@dataclass(frozen=True)
class ArchiveReceipt:
    drive_file_id: str
    drive_folder_id: str
    md5: str
    size: int
    verified_at: str
    reused_existing: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def compute_md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


def strip_coordinate_like(text: str) -> str:
    """Remove decimal numbers shaped like coordinates (e.g. ``-12.3456``)."""
    return _COORDINATE_LIKE.sub("_", text)


def archive_filename(display_filename: str, sha256: str) -> str:
    name = strip_coordinate_like(display_filename).strip(" ._") or "original"
    return name[:200] or f"{sha256[:16]}.bin"


def _bounded_property(key: str, value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9._:-]+", "_", value)
    if _COORDINATE_LIKE.search(cleaned):
        return None
    room = _APP_PROPERTY_BYTES - len(key.encode())
    return cleaned[:room] or None


def load_authorized_user_info(raw: str) -> dict[str, Any]:
    """Parse and check ``FIELD_MEDIA_DRIVE_CREDENTIALS_JSON``. Never echoes the value."""
    try:
        info = json.loads(raw)
    except (TypeError, ValueError):
        raise ArchiveConfigError("FIELD_MEDIA_DRIVE_CREDENTIALS_JSON is not valid JSON") from None
    if not isinstance(info, dict):
        raise ArchiveConfigError("FIELD_MEDIA_DRIVE_CREDENTIALS_JSON must be a JSON object")
    credential_type = info.get("type")
    if credential_type == "service_account":
        raise ArchiveConfigError(SERVICE_ACCOUNT_REJECTION)
    if credential_type not in (None, "authorized_user"):
        raise ArchiveConfigError("FIELD_MEDIA_DRIVE_CREDENTIALS_JSON must be authorized_user JSON")
    missing = [key for key in ("client_id", "client_secret", "refresh_token") if not info.get(key)]
    if missing:
        raise ArchiveConfigError(
            "FIELD_MEDIA_DRIVE_CREDENTIALS_JSON is missing: " + ", ".join(missing)
        )
    return {**info, "type": "authorized_user"}


class DriveMediaArchive:
    def __init__(
        self,
        gateway: DriveArchiveGateway,
        *,
        folder_name: str = DEFAULT_FOLDER_NAME,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.gateway = gateway
        self.folder_name = folder_name
        self.timeout_seconds = timeout_seconds
        self._root_id: str | None = None
        self._lock = threading.Lock()

    # -- folders -----------------------------------------------------------------------

    @staticmethod
    def _oldest(items: list[dict[str, Any]]) -> dict[str, Any] | None:
        live = [item for item in items if not item.get("trashed")]
        if not live:
            return None
        return min(live, key=lambda item: (str(item.get("createdTime") or ""), str(item["id"])))

    def find_root_folder(self) -> str | None:
        """Read-only lookup of the archive's own root folder (used by the status probe)."""
        found = self._oldest(
            self.gateway.find(app_properties={MARKER_KEY: MARKER_ROOT}, parent_id=None, folders_only=True)
        )
        return str(found["id"]) if found else None

    def _ensure_root(self) -> str:
        if self._root_id:
            return self._root_id
        root_id = self.find_root_folder()
        if root_id is None:
            created = self.gateway.create_folder(
                name=self.folder_name, parent_id=None, app_properties={MARKER_KEY: MARKER_ROOT}
            )
            root_id = str(created["id"])
        self._root_id = root_id
        return root_id

    def _ensure_observation_folder(self, root_id: str, observation_id: str) -> str:
        properties = {MARKER_KEY: MARKER_OBSERVATION, "oc_observation_id": observation_id}
        found = self._oldest(self.gateway.find(app_properties=properties, parent_id=root_id, folders_only=True))
        if found:
            return str(found["id"])
        created = self.gateway.create_folder(name=observation_id, parent_id=root_id, app_properties=properties)
        return str(created["id"])

    # -- archive and readback --------------------------------------------------------------

    @staticmethod
    def _matches(item: Mapping[str, Any], md5: str, size: int) -> bool:
        try:
            remote_size = int(item.get("size")) if item.get("size") is not None else None
        except (TypeError, ValueError):
            remote_size = None
        return str(item.get("md5Checksum") or "").lower() == md5 and remote_size == size

    def archive(
        self,
        *,
        observation_id: str,
        data: bytes,
        sha256: str,
        display_filename: str,
        mime_type: str,
        client_media_id: str | None = None,
    ) -> ArchiveReceipt:
        """Upload (or reuse) one original and verify Drive's checksum before returning."""
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ArchiveError(ERROR_VERIFICATION_FAILED, "local bytes do not match the recorded sha256")
        md5 = compute_md5(data)
        size = len(data)
        with self._lock:
            root_id = self._ensure_root()
            folder_id = self._ensure_observation_folder(root_id, observation_id)
            existing = self.gateway.find(
                app_properties={MARKER_KEY: MARKER_ORIGINAL, "oc_sha256": sha256},
                parent_id=folder_id,
                folders_only=False,
            )
            for item in existing:
                if not item.get("trashed") and self._matches(item, md5, size):
                    return ArchiveReceipt(str(item["id"]), folder_id, md5, size, _now_iso(), reused_existing=True)
            properties: dict[str, str] = {
                MARKER_KEY: MARKER_ORIGINAL,
                "oc_observation_id": observation_id,
                "oc_sha256": sha256,
            }
            client_property = _bounded_property("oc_client_media_id", client_media_id)
            if client_property:
                properties["oc_client_media_id"] = client_property
            uploaded = self.gateway.upload(
                name=archive_filename(display_filename, sha256),
                parent_id=folder_id,
                data=data,
                mime_type=mime_type or "application/octet-stream",
                app_properties=properties,
            )
        if not self._matches(uploaded, md5, size):
            raise ArchiveError(ERROR_VERIFICATION_FAILED, "Drive checksum or size differs from the local original")
        return ArchiveReceipt(str(uploaded["id"]), folder_id, md5, size, _now_iso())

    def fetch(self, receipt: Mapping[str, Any], *, expected_sha256: str) -> bytes:
        """Download a verified copy and check md5, size and sha256 before returning it."""
        file_id = str(receipt.get("drive_file_id") or "")
        if not file_id:
            raise ArchiveError(ERROR_VERIFICATION_FAILED, "receipt has no drive_file_id")
        with self._lock:
            data = self.gateway.download(file_id)
        if (
            compute_md5(data) != str(receipt.get("md5") or "").lower()
            or len(data) != int(receipt.get("size") or -1)
            or hashlib.sha256(data).hexdigest() != expected_sha256
        ):
            raise ArchiveError(ERROR_VERIFICATION_FAILED, "Drive copy failed verification on read")
        return data


class GoogleDriveArchiveGateway:
    """Drive v3 adapter. Only files().list/create/get_media are used; never permissions()."""

    FILE_FIELDS = "id,name,mimeType,md5Checksum,size,parents,appProperties,createdTime,trashed"

    def __init__(self, service: Any) -> None:
        self.service = service

    @classmethod
    def from_authorized_user_info(cls, info: Mapping[str, Any], *, timeout_seconds: float) -> GoogleDriveArchiveGateway:
        try:
            import google_auth_httplib2
            import httplib2
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover - dependencies are in requirements.txt
            raise ArchiveConfigError("Google Drive client libraries are not installed") from exc
        credentials = Credentials.from_authorized_user_info(dict(info), scopes=[DRIVE_FILE_SCOPE])
        http = google_auth_httplib2.AuthorizedHttp(credentials, http=httplib2.Http(timeout=timeout_seconds))
        return cls(build("drive", "v3", http=http, cache_discovery=False))

    @staticmethod
    def _literal(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def build_query(
        self, *, app_properties: Mapping[str, str], parent_id: str | None, folders_only: bool
    ) -> str:
        if not app_properties:
            raise ValueError("archive queries must be scoped by an appProperties marker")
        clauses = [
            f"appProperties has {{ key='{self._literal(k)}' and value='{self._literal(v)}' }}"
            for k, v in sorted(app_properties.items())
        ]
        if parent_id:
            clauses.append(f"'{self._literal(parent_id)}' in parents")
        clauses.append(f"mimeType {'=' if folders_only else '!='} '{FOLDER_MIME}'")
        clauses.append("trashed = false")
        return " and ".join(clauses)

    def find(
        self, *, app_properties: Mapping[str, str], parent_id: str | None, folders_only: bool
    ) -> list[dict[str, Any]]:
        query = self.build_query(app_properties=app_properties, parent_id=parent_id, folders_only=folders_only)
        found: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            response = self.service.files().list(
                q=query,
                spaces="drive",
                fields=f"nextPageToken,files({self.FILE_FIELDS})",
                pageSize=100,
                pageToken=token,
            ).execute(num_retries=2)
            found.extend(response.get("files", []))
            token = response.get("nextPageToken")
            if not token or len(found) >= 1000:
                return found

    def create_folder(
        self, *, name: str, parent_id: str | None, app_properties: Mapping[str, str]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME, "appProperties": dict(app_properties)}
        if parent_id:
            body["parents"] = [parent_id]
        return self.service.files().create(body=body, fields=self.FILE_FIELDS).execute(num_retries=2)

    def upload(
        self,
        *,
        name: str,
        parent_id: str,
        data: bytes,
        mime_type: str,
        app_properties: Mapping[str, str],
    ) -> dict[str, Any]:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type, chunksize=8 * 1024 * 1024, resumable=True)
        body = {"name": name, "parents": [parent_id], "appProperties": dict(app_properties)}
        return self.service.files().create(body=body, media_body=media, fields=self.FILE_FIELDS).execute(num_retries=2)

    def download(self, file_id: str) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload

        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, self.service.files().get_media(fileId=file_id), chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk(num_retries=2)
        return buffer.getvalue()


# -- configuration ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ArchiveConfig:
    archive: DriveMediaArchive | None
    error_code: str | None

    @property
    def configured(self) -> bool:
        return self.archive is not None


_UNSET = object()
_override: Any = _UNSET
_cache: tuple[str, ArchiveConfig] | None = None
_cache_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="field-media-drive")
T = TypeVar("T")


def configure_archive(archive: DriveMediaArchive | None | object = _UNSET) -> None:
    """Inject an archive (tests pass one built on a fake gateway). No argument resets to env."""
    global _override, _cache
    _override = archive
    _cache = None


def archive_timeout_seconds() -> float:
    raw = os.environ.get("FIELD_MEDIA_DRIVE_TIMEOUT_SECONDS", "").strip()
    try:
        value = float(raw) if raw else DEFAULT_TIMEOUT_SECONDS
    except ValueError:
        value = DEFAULT_TIMEOUT_SECONDS
    return min(max(value, 1.0), MAX_TIMEOUT_SECONDS)


def get_field_media_archive() -> ArchiveConfig:
    """The configured archive, ``None`` when unset, or an error code when credentials are unusable."""
    global _cache
    if _override is not _UNSET:
        return ArchiveConfig(_override if isinstance(_override, DriveMediaArchive) else None, None)
    raw = (os.environ.get("FIELD_MEDIA_DRIVE_CREDENTIALS_JSON") or "").strip()
    if not raw:
        return ArchiveConfig(None, None)
    folder_name = (os.environ.get("FIELD_MEDIA_DRIVE_FOLDER_NAME") or "").strip() or DEFAULT_FOLDER_NAME
    timeout = archive_timeout_seconds()
    fingerprint = hashlib.sha256(f"{raw}\n{folder_name}\n{timeout}".encode()).hexdigest()
    with _cache_lock:
        if _cache is not None and _cache[0] == fingerprint:
            return _cache[1]
        try:
            info = load_authorized_user_info(raw)
            gateway = GoogleDriveArchiveGateway.from_authorized_user_info(info, timeout_seconds=timeout)
            config = ArchiveConfig(DriveMediaArchive(gateway, folder_name=folder_name, timeout_seconds=timeout), None)
        except Exception:  # noqa: BLE001 - never surface credential parsing detail
            config = ArchiveConfig(None, ERROR_CREDENTIALS_INVALID)
        _cache = (fingerprint, config)
        return config


def submit_bounded(fn: Callable[[], T]):
    """Run a Drive call on the bounded archive pool; callers wait with their own timeout."""
    return _executor.submit(fn)


def error_code_for(exc: BaseException) -> str:
    if isinstance(exc, ArchiveError):
        return exc.error_code
    if isinstance(exc, ArchiveConfigError):
        return ERROR_CREDENTIALS_INVALID
    if isinstance(exc, TimeoutError):
        return ERROR_TIMEOUT
    name = type(exc).__name__
    if name in {"RefreshError", "DefaultCredentialsError"}:
        return ERROR_CREDENTIALS_INVALID
    if "timeout" in name.lower():
        return ERROR_TIMEOUT
    return ERROR_UNAVAILABLE
