from __future__ import annotations

import hashlib
import os
from typing import Any

from .drive import format_for
from .models import ImportResult, ImportState, RegistryDocument

IMPORTER_VERSION = "BUILD-082.1"
DEFAULT_BATCH_LIMIT = 25


class DocumentImportService:
    def __init__(self, repository: Any, gateway: Any, *, pilot_folder: str | None = None, batch_limit: int = DEFAULT_BATCH_LIMIT):
        self.repository = repository
        self.gateway = gateway
        self.pilot_folder = pilot_folder or os.getenv("GOOGLE_DRIVE_PILOT_FOLDER", "/Pilot/")
        self.batch_limit = batch_limit

    def preview(self, registry_id: int, actor: str) -> dict[str, Any]:
        document = self._approved_document(registry_id, actor)
        extension, output_mime, export_format = format_for(document.mime_type)
        latest = self.repository.latest_revision(registry_id)
        return {
            "registry_id": registry_id, "state": ImportState.READY.value, "filename": document.filename,
            "mime_type": document.mime_type, "output_mime_type": output_mime, "extension": extension,
            "export_format": export_format, "folder": document.folder, "previous_revision": latest,
            "content_retrieved": False,
        }

    def import_one(self, registry_id: int, actor: str, *, mission_id: int | None = None, session_id: int | None = None) -> ImportResult:
        document = self._approved_document(registry_id, actor)
        session_id = session_id or self.repository.create_session(actor, [registry_id], mission_id, IMPORTER_VERSION)
        self.repository.transition(session_id, registry_id, ImportState.REGISTERED, ImportState.READY, actor)
        if self.repository.is_cancelled(session_id):
            self.repository.transition(session_id, registry_id, ImportState.READY, ImportState.CANCELLED, actor)
            return ImportResult(session_id, registry_id, ImportState.CANCELLED)
        self.repository.transition(session_id, registry_id, ImportState.READY, ImportState.IMPORTING, actor)
        try:
            retrieved = self.gateway.retrieve(document)
            digest = hashlib.sha256(retrieved.content).hexdigest()
            if len(digest) != 64:
                raise ValueError("HASH_VALIDATION_FAILED")
            result = self.repository.persist_import(
                session_id=session_id, document=document, retrieved=retrieved, sha256=digest,
                actor=actor, mission_id=mission_id, importer_version=IMPORTER_VERSION,
            )
            self.repository.transition(session_id, registry_id, ImportState.IMPORTING, result.state, actor, revision_id=result.revision_id)
            return result
        except RuntimeError as exc:
            state = ImportState.RETRYABLE if str(exc) == "DRIVE_RETRIEVAL_RETRYABLE" else ImportState.FAILED
            self.repository.record_failure(session_id, registry_id, str(exc), state)
            self.repository.transition(session_id, registry_id, ImportState.IMPORTING, state, actor, reason=str(exc))
            return ImportResult(session_id, registry_id, state, error_code=str(exc))
        except Exception as exc:
            self.repository.record_failure(session_id, registry_id, exc.__class__.__name__, ImportState.FAILED)
            self.repository.transition(session_id, registry_id, ImportState.IMPORTING, ImportState.FAILED, actor, reason=exc.__class__.__name__)
            return ImportResult(session_id, registry_id, ImportState.FAILED, error_code=exc.__class__.__name__)

    def import_batch(self, registry_ids: list[int], actor: str, *, mission_id: int | None = None) -> dict[str, Any]:
        if not registry_ids or len(registry_ids) > self.batch_limit:
            raise ValueError("BATCH_LIMIT_EXCEEDED")
        if len(set(registry_ids)) != len(registry_ids):
            raise ValueError("DUPLICATE_REGISTRY_ID")
        for registry_id in registry_ids:
            self._approved_document(registry_id, actor)
        session_id = self.repository.create_session(actor, registry_ids, mission_id, IMPORTER_VERSION)
        results = [self.import_one(item, actor, mission_id=mission_id, session_id=session_id).as_dict() for item in registry_ids]
        return {"session_id": session_id, "results": results}

    def retry(self, session_id: int, registry_id: int, actor: str) -> ImportResult:
        if not self.repository.can_retry(session_id, registry_id):
            raise ValueError("IMPORT_NOT_RETRYABLE")
        self.repository.increment_retry(session_id, registry_id, actor)
        return self.import_one(registry_id, actor)

    def cancel(self, session_id: int, actor: str) -> dict[str, Any]:
        return self.repository.cancel_session(session_id, actor)

    def _approved_document(self, registry_id: int, actor: str) -> RegistryDocument:
        document = self.repository.get_registry_document(registry_id)
        if document is None:
            raise LookupError("REGISTRY_ITEM_NOT_FOUND")
        if not self.repository.actor_owns_source(actor, document.source_id):
            raise PermissionError("SOURCE_OWNERSHIP_REQUIRED")
        if document.folder.rstrip("/") != self.pilot_folder.rstrip("/"):
            raise PermissionError("PILOT_FOLDER_REQUIRED")
        format_for(document.mime_type)
        return document


def validate_mission_payload(payload: Any) -> list[int]:
    if not isinstance(payload, dict) or set(payload) != {"registry_ids"}:
        raise ValueError("INVALID_DRIVE_IMPORT_MISSION_PAYLOAD")
    ids = payload["registry_ids"]
    if not isinstance(ids, list) or not ids or any(not isinstance(item, int) or item <= 0 for item in ids):
        raise ValueError("INVALID_DRIVE_IMPORT_MISSION_PAYLOAD")
    return ids
