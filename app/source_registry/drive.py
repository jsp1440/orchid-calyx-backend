from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Protocol

from .models import DriveFile

FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_NATIVE_PREFIX = "application/vnd.google-apps."
FILE_FIELDS = "id,name,mimeType,size,md5Checksum,sha1Checksum,sha256Checksum,createdTime,modifiedTime,version,headRevisionId,parents,trashed"


class DriveGateway(Protocol):
    def children(self, folder_id: str) -> list[dict[str, Any]]: ...


def _date(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _native_key(item: dict[str, Any]) -> str | None:
    mime = str(item.get("mimeType") or "")
    if not mime.startswith(GOOGLE_NATIVE_PREFIX) or mime == FOLDER_MIME:
        return None
    # Google-native files have no byte checksum. This conservative metadata
    # fingerprint detects copies retaining the same title/type/size signature;
    # it never claims content equivalence across unlike metadata.
    normalized_name = " ".join(str(item.get("name") or "").casefold().split())
    material = json.dumps([mime, normalized_name, item.get("size")], separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()


def walk_drive(gateway: DriveGateway, folder_ids: list[str]) -> Iterator[DriveFile]:
    """Depth-first metadata walk. No download/export/content API is invoked."""
    stack = [(folder_id, "/") for folder_id in reversed(folder_ids)]
    visited: set[str] = set()
    while stack:
        folder_id, path = stack.pop()
        if folder_id in visited:
            continue
        visited.add(folder_id)
        children = gateway.children(folder_id)
        for item in children:
            if item.get("trashed"):
                continue
            name = str(item.get("name") or "unnamed")
            if item.get("mimeType") == FOLDER_MIME:
                stack.append((str(item["id"]), f"{path}{name}/"))
                continue
            checksum = item.get("sha256Checksum") or item.get("md5Checksum") or item.get("sha1Checksum")
            yield DriveFile(
                file_id=str(item["id"]), filename=name, folder_path=path,
                mime_type=str(item.get("mimeType") or "application/octet-stream"),
                size=int(item["size"]) if item.get("size") is not None else None,
                checksum=str(checksum) if checksum else None,
                created_at=_date(item.get("createdTime")), modified_at=_date(item.get("modifiedTime")),
                version=str(item.get("version") or item.get("headRevisionId") or "") or None,
                native_duplicate_key=_native_key(item), raw_metadata={"parents": item.get("parents", [])},
            )


class GoogleApiDriveGateway:
    def __init__(self, service: Any):
        self.service = service

    @classmethod
    def from_environment(cls) -> "GoogleApiDriveGateway":
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            import google.auth
        except ImportError as exc:
            raise RuntimeError("Google Drive dependencies are not installed") from exc
        scopes = ["https://www.googleapis.com/auth/drive.metadata.readonly"]
        credentials_json = os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON")
        if credentials_json:
            credentials = service_account.Credentials.from_service_account_info(json.loads(credentials_json), scopes=scopes)
        else:
            credentials, _ = google.auth.default(scopes=scopes)
        return cls(build("drive", "v3", credentials=credentials, cache_discovery=False))

    def children(self, folder_id: str) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        token = None
        while True:
            response = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed = false", fields=f"nextPageToken,files({FILE_FIELDS})",
                pageSize=1000, pageToken=token, supportsAllDrives=True, includeItemsFromAllDrives=True,
                corpora="allDrives",
            ).execute()
            result.extend(response.get("files", []))
            token = response.get("nextPageToken")
            if not token:
                return result

