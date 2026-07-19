from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class InventoryStatus(StrEnum):
    NEW = "NEW"
    SCANNED = "SCANNED"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    DUPLICATE = "DUPLICATE"
    CHANGED = "CHANGED"


@dataclass(frozen=True)
class DriveFile:
    file_id: str
    filename: str
    folder_path: str
    mime_type: str
    size: int | None
    checksum: str | None
    created_at: datetime | None
    modified_at: datetime | None
    version: str | None = None
    native_duplicate_key: str | None = None
    raw_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class ScanResult:
    source_id: str
    scan_id: int
    discovered: int
    processed: int
    unchanged: int
    duplicates: int
    failed: int
    duration_ms: int

