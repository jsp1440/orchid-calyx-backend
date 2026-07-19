from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import DriveFile, InventoryStatus


def database_url() -> str:
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for source registry operations")
    return value


class PostgresSourceRegistryRepository:
    def register_google_drive(self, name: str, authentication_method: str, folder_ids: list[str]) -> dict[str, Any]:
        with psycopg.connect(database_url(), row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO oc_sources.sources(source_name,source_type,authentication_method,status,configuration)
                VALUES (%s,'GOOGLE_DRIVE',%s,'ACTIVE',%s)
                ON CONFLICT (source_name,source_type) DO UPDATE SET authentication_method=EXCLUDED.authentication_method,
                configuration=EXCLUDED.configuration, updated_at=NOW() RETURNING *""",
                (name, authentication_method, Jsonb({"folder_ids": folder_ids})))
            return cur.fetchone()

    def list_sources(self) -> list[dict[str, Any]]:
        with psycopg.connect(database_url(), row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_sources.sources ORDER BY source_name")
            return list(cur.fetchall())

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with psycopg.connect(database_url(), row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_sources.sources WHERE source_id=%s", (source_id,))
            return cur.fetchone()

    def start_scan(self, source_id: str) -> int:
        with psycopg.connect(database_url(), row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO oc_sources.scan_logs(source_id,status,started_at) VALUES (%s,'RUNNING',NOW()) RETURNING scan_id", (source_id,))
            return cur.fetchone()["scan_id"]

    def inventory_file(self, source_id: str, scan_id: int, file: DriveFile) -> str:
        with psycopg.connect(database_url(), row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_sources.document_inventory WHERE source_id=%s AND external_file_id=%s FOR UPDATE", (source_id, file.file_id))
            existing = cur.fetchone()
            unchanged = existing and existing["modified_at"] == file.modified_at and existing["checksum"] == file.checksum and existing["filename"] == file.filename and existing["folder_path"] == file.folder_path
            if unchanged:
                cur.execute("UPDATE oc_sources.document_inventory SET last_seen_scan_id=%s,last_seen_at=NOW() WHERE inventory_id=%s", (scan_id, existing["inventory_id"]))
                return "UNCHANGED"
            duplicate = None
            if file.checksum:
                cur.execute("SELECT inventory_id FROM oc_sources.document_inventory WHERE checksum=%s AND NOT (source_id=%s AND external_file_id=%s) ORDER BY inventory_id LIMIT 1", (file.checksum, source_id, file.file_id))
                duplicate = cur.fetchone()
            elif file.native_duplicate_key:
                cur.execute("SELECT inventory_id FROM oc_sources.document_inventory WHERE native_duplicate_key=%s AND NOT (source_id=%s AND external_file_id=%s) ORDER BY inventory_id LIMIT 1", (file.native_duplicate_key, source_id, file.file_id))
                duplicate = cur.fetchone()
            status = InventoryStatus.DUPLICATE.value if duplicate else (InventoryStatus.CHANGED.value if existing else InventoryStatus.SCANNED.value)
            cur.execute("""INSERT INTO oc_sources.document_inventory
                (source_id,external_file_id,filename,folder_path,mime_type,byte_size,checksum,created_at,modified_at,drive_version,native_duplicate_key,status,duplicate_of_id,first_seen_scan_id,last_seen_scan_id,provenance)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_id,external_file_id) DO UPDATE SET filename=EXCLUDED.filename,folder_path=EXCLUDED.folder_path,
                mime_type=EXCLUDED.mime_type,byte_size=EXCLUDED.byte_size,checksum=EXCLUDED.checksum,modified_at=EXCLUDED.modified_at,
                drive_version=EXCLUDED.drive_version,native_duplicate_key=EXCLUDED.native_duplicate_key,status=EXCLUDED.status,
                duplicate_of_id=EXCLUDED.duplicate_of_id,last_seen_scan_id=EXCLUDED.last_seen_scan_id,last_seen_at=NOW(),provenance=EXCLUDED.provenance""",
                (source_id,file.file_id,file.filename,file.folder_path,file.mime_type,file.size,file.checksum,file.created_at,file.modified_at,file.version,file.native_duplicate_key,status,duplicate["inventory_id"] if duplicate else None,scan_id,scan_id,Jsonb({"provider":"google_drive","file_id":file.file_id,"metadata_only":True,**(file.raw_metadata or {})})))
            return status

    def finish_scan(self, scan_id: int, source_id: str, status: str, processed: int, unchanged: int, duplicates: int, failed: int, error: str | None = None) -> None:
        with psycopg.connect(database_url(), row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("""UPDATE oc_sources.scan_logs SET status=%s,finished_at=NOW(),duration_ms=(EXTRACT(EPOCH FROM (NOW()-started_at))*1000)::BIGINT,
                documents_processed=%s,documents_unchanged=%s,duplicates_found=%s,documents_failed=%s,error_message=%s WHERE scan_id=%s""", (status,processed,unchanged,duplicates,failed,error,scan_id))
            cur.execute("""UPDATE oc_sources.sources s SET last_scan=NOW(), status=%s,
                total_documents=(SELECT count(*) FROM oc_sources.document_inventory d WHERE d.source_id=s.source_id),
                total_processed=(SELECT count(*) FROM oc_sources.document_inventory d WHERE d.source_id=s.source_id AND d.status='PROCESSED'),
                total_failed=(SELECT count(*) FROM oc_sources.document_inventory d WHERE d.source_id=s.source_id AND d.status='FAILED'), updated_at=NOW()
                WHERE source_id=%s""", ("ACTIVE" if status == "COMPLETED" else "ERROR", source_id))

    def dashboard(self) -> dict[str, Any]:
        with psycopg.connect(database_url(), row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("""SELECT count(*) total_sources,coalesce(sum(total_documents),0) total_documents,
                coalesce(sum(total_processed),0) documents_processed,max(last_scan) last_scan_time FROM oc_sources.sources""")
            summary = cur.fetchone()
            cur.execute("""SELECT count(*) FILTER (WHERE status='DUPLICATE') duplicates,count(*) FILTER (WHERE status='FAILED') failed_files,
                count(*) FILTER (WHERE status IN ('NEW','SCANNED','CHANGED')) processing_queue FROM oc_sources.document_inventory""")
            return {**summary, **cur.fetchone()}

    def scan_logs(self, source_id: str, limit: int) -> list[dict[str, Any]]:
        with psycopg.connect(database_url(), row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_sources.scan_logs WHERE source_id=%s ORDER BY scan_id DESC LIMIT %s", (source_id, limit))
            return list(cur.fetchall())

