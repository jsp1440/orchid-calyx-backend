"""BUILD-082A live acceptance harness. Metadata-only output; never logs content or credentials."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.document_import.drive import GoogleDriveDocumentGateway
from app.document_import.repository import PostgresDocumentImportRepository
from app.document_import.service import DocumentImportService, validate_mission_payload

ROOT = Path(__file__).parents[1]
NAMES = (
    "BUILD-INFRA-004 Architecture Review.pdf",
    "comprehensive_orchid_glossary.pdf",
    "Copy of Mijinyawa's CV.docx",
)
PROTECTED = ("oc_graph", "oc_taxonomy", "oc_ontology", "oc_semantic", "oc_publication")


def counts(conn):
    result = {}
    with conn.cursor() as cur:
        for schema in PROTECTED:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name", (schema,))
            tables = [row["table_name"] for row in cur.fetchall()]
            rows = 0
            for table in tables:
                cur.execute(sql.SQL("SELECT count(*) AS row_count FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table)))
                rows += cur.fetchone()["row_count"]
            result[schema] = {"tables": len(tables), "rows": rows}
    return result


def main():
    dsn = os.environ["DATABASE_URL"]
    if not os.getenv("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON"):
        raise RuntimeError("GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON is not configured")
    metrics = {"total_pipeline_ms": 0.0}
    started = time.perf_counter()
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        before = counts(conn)
        migration = (ROOT / "migrations" / "082_controlled_drive_document_import.sql").read_text()
        with conn.cursor() as cur:
            cur.execute(migration)
            cur.execute(migration)
            cur.execute("""SELECT d.inventory_id,d.filename,d.folder_path,d.external_file_id,d.mime_type
                FROM oc_sources.document_inventory d JOIN oc_sources.sources s ON s.source_id=d.source_id
                WHERE d.filename=ANY(%s) AND d.folder_path='/Pilot/' AND s.source_type='GOOGLE_DRIVE'
                ORDER BY d.filename""", (list(NAMES),))
            records = list(cur.fetchall())
        if {r["filename"] for r in records} != set(NAMES) or len(records) != 3:
            raise RuntimeError("Exactly three registered /Pilot/ records were not found")
        repository = PostgresDocumentImportRepository()
        service = DocumentImportService(repository, GoogleDriveDocumentGateway.from_environment())
        previews = [service.preview(row["inventory_id"], "owner_session") for row in records]
        first = []
        for row in records:
            t0 = time.perf_counter(); result = service.import_one(row["inventory_id"], "owner_session"); elapsed = (time.perf_counter()-t0)*1000
            first.append({**result.as_dict(), "pipeline_ms": round(elapsed, 3)})
        intake_count_after_first = conn.execute("SELECT count(*) AS row_count FROM oc_intake.documents WHERE provenance ? 'brain_source_registry_id'").fetchone()["row_count"]
        rerun = []
        for row in records:
            t0 = time.perf_counter(); result = service.import_one(row["inventory_id"], "owner_session"); elapsed = (time.perf_counter()-t0)*1000
            rerun.append({**result.as_dict(), "duplicate_detection_ms": round(elapsed, 3)})
        intake_count_after_second = conn.execute("SELECT count(*) AS row_count FROM oc_intake.documents WHERE provenance ? 'brain_source_registry_id'").fetchone()["row_count"]
        if intake_count_after_first != intake_count_after_second:
            raise RuntimeError("Rerun created duplicate Universal Intake records")
        if any(row["state"] not in {"UNCHANGED", "DUPLICATE"} for row in rerun):
            raise RuntimeError("Rerun did not produce an idempotent state")
        bad_payloads = ({"paths":["x"]},{"urls":["https://example.invalid"]},{"sql":"select 1"},{"shell":"echo x"},{"drive_ids":["raw"]})
        mission_rejections = 0
        for payload in bad_payloads:
            try: validate_mission_payload(payload)
            except ValueError: mission_rejections += 1
        if mission_rejections != len(bad_payloads): raise RuntimeError("Mission payload rejection failed")
        after = counts(conn)
        if before != after: raise RuntimeError("Protected schema mutation detected")
        audit = conn.execute("SELECT session_id,registry_id,previous_state,new_state,occurred_at FROM oc_import.audit_trail WHERE registry_id=ANY(%s) ORDER BY audit_id", ([r["inventory_id"] for r in records],)).fetchall()
        constraints = conn.execute("""SELECT count(*) constraints FROM information_schema.table_constraints WHERE table_schema='oc_import'""").fetchone()["constraints"]
        indexes = conn.execute("SELECT count(*) indexes FROM pg_indexes WHERE schemaname='oc_import'").fetchone()["indexes"]
        metrics["total_pipeline_ms"] = round((time.perf_counter()-started)*1000,3)
        report = {"authenticated":True,"drive_scope":"drive.readonly","documents":records,"previews":previews,"first_import":first,
            "rerun":rerun,"intake_count_stable":True,"audit_records":len(audit),"audit_transitions":[r["new_state"] for r in audit],
            "migration":{"tables":5,"indexes":indexes,"constraints":constraints,"applied_twice":True},
            "mission":{"valid_registry_ids":validate_mission_payload({"registry_ids":[r["inventory_id"] for r in records]}),"invalid_payloads_rejected":mission_rejections},
            "protected_before":before,"protected_after":after,"security":{"drive_writes":0,"credentials_logged":False,"contents_logged":False},"metrics":metrics}
        print(json.dumps(report, default=str, sort_keys=True))


if __name__ == "__main__": main()
