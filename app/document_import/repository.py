from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import ImportResult, ImportState, RegistryDocument


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for document import")
    return value


class PostgresDocumentImportRepository:
    def _connect(self):
        return psycopg.connect(database_url(), row_factory=dict_row)

    def get_registry_document(self, registry_id: int) -> RegistryDocument | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT d.inventory_id,d.source_id,d.external_file_id,d.filename,d.folder_path,d.mime_type,
                d.created_at,d.modified_at,d.provenance,s.configuration FROM oc_sources.document_inventory d
                JOIN oc_sources.sources s ON s.source_id=d.source_id WHERE d.inventory_id=%s""", (registry_id,))
            row = cur.fetchone()
            if not row: return None
            provenance, configuration = row["provenance"] or {}, row["configuration"] or {}
            return RegistryDocument(row["inventory_id"], str(row["source_id"]), row["external_file_id"],
                f"https://drive.google.com/open?id={row['external_file_id']}", row["filename"], row["mime_type"],
                row["folder_path"], provenance.get("owner") or configuration.get("owner"), row["created_at"], row["modified_at"])

    def actor_owns_source(self, actor: str, source_id: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT configuration FROM oc_sources.sources WHERE source_id=%s", (source_id,))
            row = cur.fetchone()
            if not row: return False
            owners = (row["configuration"] or {}).get("approved_importers", [])
            return actor in owners or actor in {"owner_session", "api_key", "backend_api_key", "owner"}

    def create_session(self, actor: str, registry_ids: list[int], mission_id: int | None, version: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO oc_import.import_sessions(authenticated_user,registry_ids,mission_id,importer_version,state)
                VALUES (%s,%s,%s,%s,'REGISTERED') RETURNING session_id""", (actor, registry_ids, mission_id, version))
            session_id = cur.fetchone()["session_id"]
            cur.execute("""INSERT INTO oc_import.audit_trail(session_id,registry_id,previous_state,new_state,actor,reason)
                SELECT %s,value,NULL,'REGISTERED',%s,'explicit owner-approved import session' FROM unnest(%s::bigint[]) value""", (session_id,actor,registry_ids))
            return session_id

    def transition(self, session_id: int, registry_id: int, previous: ImportState | None, target: ImportState, actor: str, *, reason: str | None = None, revision_id: int | None = None) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO oc_import.audit_trail(session_id,registry_id,revision_id,previous_state,new_state,actor,reason)
                VALUES (%s,%s,%s,%s,%s,%s,%s)""", (session_id, registry_id, revision_id, previous.value if previous else None, target.value, actor, reason))
            cur.execute("UPDATE oc_import.import_sessions SET state=%s,updated_at=NOW() WHERE session_id=%s", (target.value, session_id))

    def latest_revision(self, registry_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT revision_id,revision_number,sha256,imported_at FROM oc_import.document_revisions WHERE registry_id=%s ORDER BY revision_number DESC LIMIT 1", (registry_id,))
            return cur.fetchone()

    def persist_import(self, *, session_id: int, document: RegistryDocument, retrieved: Any, sha256: str, actor: str, mission_id: int | None, importer_version: str) -> ImportResult:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_import.document_revisions WHERE registry_id=%s ORDER BY revision_number DESC LIMIT 1 FOR UPDATE", (document.registry_id,))
            latest = cur.fetchone()
            if latest and latest["sha256"] == sha256:
                return ImportResult(session_id, document.registry_id, ImportState.UNCHANGED, latest["revision_id"], latest["intake_document_id"], sha256, len(retrieved.content), latest["revision_number"])
            cur.execute("SELECT revision_id,intake_document_id FROM oc_import.document_revisions WHERE sha256=%s ORDER BY revision_id LIMIT 1", (sha256,))
            duplicate = cur.fetchone()
            revision_number = (latest["revision_number"] + 1) if latest else 1
            state = ImportState.DUPLICATE if duplicate else ImportState.IMPORTED
            cur.execute("""INSERT INTO oc_intake.ingestion_batches(display_name,uploader,source_label,status,file_count,accepted_count,duplicate_count,completed_at)
                VALUES (%s,%s,'GOOGLE_DRIVE','COMPLETED',1,%s,%s,NOW()) RETURNING id""",
                (f"Drive import session {session_id}", actor, 0 if duplicate else 1, 1 if duplicate else 0))
            batch_id = cur.fetchone()["id"]
            provenance = {"brain_source_registry_id":document.registry_id,"google_drive_file_id":document.drive_file_id,
                "drive_url":document.drive_url,"file_name":document.filename,"mime_type":document.mime_type,
                "export_format":retrieved.export_format,"folder":document.folder,"owner":document.owner,
                "created_timestamp":document.created_at.isoformat() if document.created_at else None,
                "modified_timestamp":document.modified_at.isoformat() if document.modified_at else None,
                "sha256":sha256,"byte_count":len(retrieved.content),"importer_version":importer_version,
                "mission_id":mission_id,"authenticated_user":actor,"import_session":session_id}
            cur.execute("""INSERT INTO oc_intake.documents(batch_id,original_filename,display_title,media_type,extension,byte_size,sha256,storage_key,uploader,
                processing_status,text_extraction_status,preliminary_document_type,relevance,review_status,duplicate_of_id,canonical_promotion_prohibited,provenance)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'PROCESSED','NOT_REQUESTED','unknown','UNKNOWN',%s,%s,TRUE,%s) RETURNING id""",
                (batch_id,document.filename,document.filename,retrieved.output_mime_type,retrieved.extension,len(retrieved.content),sha256,
                 f"drive-import://session/{session_id}/registry/{document.registry_id}/revision/{revision_number}",actor,state.value,
                 duplicate["intake_document_id"] if duplicate else None,Jsonb(provenance)))
            intake_id = cur.fetchone()["id"]
            cur.execute("""INSERT INTO oc_import.document_revisions(session_id,registry_id,intake_document_id,revision_number,sha256,byte_count,content_bytes,provenance,state,duplicate_of_revision_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING revision_id""",
                (session_id,document.registry_id,intake_id,revision_number,sha256,len(retrieved.content),retrieved.content,Jsonb(provenance),state.value,duplicate["revision_id"] if duplicate else None))
            revision_id = cur.fetchone()["revision_id"]
            cur.execute("INSERT INTO oc_import.hash_index(sha256,canonical_revision_id,byte_count) VALUES (%s,%s,%s) ON CONFLICT(sha256) DO NOTHING", (sha256,revision_id,len(retrieved.content)))
            return ImportResult(session_id, document.registry_id, state, revision_id, intake_id, sha256, len(retrieved.content), revision_number, duplicate["revision_id"] if duplicate else None)

    def history(self, registry_id: int | None, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT revision_id,session_id,registry_id,intake_document_id,revision_number,sha256,byte_count,provenance,state,duplicate_of_revision_id,imported_at FROM oc_import.document_revisions WHERE (%s IS NULL OR registry_id=%s) ORDER BY imported_at DESC LIMIT %s", (registry_id, registry_id, limit))
            return list(cur.fetchall())

    def record_failure(self, session_id: int, registry_id: int, error_code: str, state: ImportState) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO oc_import.retry_tracking(session_id,registry_id,state,error_code,next_retry_at)
                VALUES (%s,%s,%s,%s,CASE WHEN %s='RETRYABLE' THEN NOW() ELSE NULL END)
                ON CONFLICT(session_id,registry_id) DO UPDATE SET state=EXCLUDED.state,error_code=EXCLUDED.error_code""", (session_id,registry_id,state.value,error_code,state.value))

    def can_retry(self, session_id: int, registry_id: int) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM oc_import.retry_tracking WHERE session_id=%s AND registry_id=%s AND state='RETRYABLE'", (session_id,registry_id))
            return cur.fetchone() is not None

    def increment_retry(self, session_id: int, registry_id: int, actor: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE oc_import.retry_tracking SET attempt_count=attempt_count+1,last_attempt_at=NOW() WHERE session_id=%s AND registry_id=%s", (session_id,registry_id))

    def is_cancelled(self, session_id: int) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT state='CANCELLED' cancelled FROM oc_import.import_sessions WHERE session_id=%s", (session_id,))
            row = cur.fetchone(); return bool(row and row["cancelled"])

    def cancel_session(self, session_id: int, actor: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""UPDATE oc_import.import_sessions SET state='CANCELLED',cancelled_at=NOW(),cancelled_by=%s,updated_at=NOW()
                WHERE session_id=%s AND state IN ('REGISTERED','READY','RETRYABLE') RETURNING session_id,state,cancelled_at""", (actor,session_id))
            row = cur.fetchone()
            if not row: raise ValueError("IMPORT_NOT_CANCELLABLE")
            cur.execute("""INSERT INTO oc_import.audit_trail(session_id,registry_id,previous_state,new_state,actor,reason)
                SELECT session_id,value,'READY','CANCELLED',%s,'owner cancellation' FROM oc_import.import_sessions,
                unnest(registry_ids) value WHERE session_id=%s""", (actor,session_id))
            return row
