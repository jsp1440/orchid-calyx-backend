from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ImportState(StrEnum):
    REGISTERED = "REGISTERED"
    READY = "READY"
    IMPORTING = "IMPORTING"
    IMPORTED = "IMPORTED"
    UNCHANGED = "UNCHANGED"
    DUPLICATE = "DUPLICATE"
    FAILED = "FAILED"
    RETRYABLE = "RETRYABLE"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class RegistryDocument:
    registry_id: int
    source_id: str
    drive_file_id: str
    drive_url: str
    filename: str
    mime_type: str
    folder: str
    owner: str | None
    created_at: datetime | None
    modified_at: datetime | None


@dataclass(frozen=True)
class RetrievedDocument:
    content: bytes
    export_format: str | None
    output_mime_type: str
    extension: str


@dataclass(frozen=True)
class ImportResult:
    session_id: int
    registry_id: int
    state: ImportState
    revision_id: int | None = None
    intake_document_id: int | None = None
    sha256: str | None = None
    byte_count: int | None = None
    revision_number: int | None = None
    duplicate_of_revision_id: int | None = None
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {key: (value.value if isinstance(value, StrEnum) else value) for key, value in self.__dict__.items()}

