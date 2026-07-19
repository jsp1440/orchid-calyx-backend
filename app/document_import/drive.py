from __future__ import annotations

import io
from typing import Any, Protocol

from .models import RegistryDocument, RetrievedDocument

GOOGLE_DOC = "application/vnd.google-apps.document"
SUPPORTED_DOWNLOADS = {
    "application/pdf": (".pdf", "application/pdf"),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "text/plain": (".txt", "text/plain"),
    "text/markdown": (".md", "text/markdown"),
    "text/x-markdown": (".md", "text/markdown"),
}


class DocumentGateway(Protocol):
    def retrieve(self, document: RegistryDocument) -> RetrievedDocument: ...


def format_for(mime_type: str) -> tuple[str, str, str | None]:
    if mime_type == GOOGLE_DOC:
        return ".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "DOCX"
    try:
        extension, output_mime = SUPPORTED_DOWNLOADS[mime_type]
    except KeyError as exc:
        raise ValueError("UNSUPPORTED_FORMAT") from exc
    return extension, output_mime, None


class GoogleDriveDocumentGateway:
    """Read-only content gateway. It exposes no Drive mutation methods."""

    def __init__(self, service: Any):
        self.service = service

    @classmethod
    def from_environment(cls) -> "GoogleDriveDocumentGateway":
        from app.source_registry.drive import GoogleApiDriveGateway
        return cls(GoogleApiDriveGateway.from_environment(scopes=["https://www.googleapis.com/auth/drive.readonly"]).service)

    def retrieve(self, document: RegistryDocument) -> RetrievedDocument:
        extension, output_mime, export_format = format_for(document.mime_type)
        if document.mime_type == GOOGLE_DOC:
            request = self.service.files().export_media(fileId=document.drive_file_id, mimeType=output_mime)
        else:
            request = self.service.files().get_media(fileId=document.drive_file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        try:
            from googleapiclient.http import MediaIoBaseDownload
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        except Exception as exc:
            if exc.__class__.__name__ in {"HttpError", "TimeoutError", "ConnectionError"}:
                raise RuntimeError("DRIVE_RETRIEVAL_RETRYABLE") from exc
            raise
        return RetrievedDocument(buffer.getvalue(), export_format, output_mime, extension)

