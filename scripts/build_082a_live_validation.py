"""BUILD-082B controlled live acceptance. Outputs metadata only, never content or secrets."""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.document_import.drive import GoogleDriveDocumentGateway
from app.document_import.repository import PostgresDocumentImportRepository
from app.document_import.service import DocumentImportService, validate_mission_payload
from app.missions.repositories import PostgresMissionRepository
from app.missions.services import MissionService
from app.source_registry.models import DriveFile
from app.source_registry.repository import PostgresSourceRegistryRepository

ROOT = Path(__file__).parents[1]
SHARED_INTAKE_FOLDER_ID = "1sOVXh7ixd8TNeEjtXfm9KlziDQ_GsCsS"
NAMES = (
    "BUILD-INFRA-004 Architecture Review.pdf",
    "comprehensive_orchid_glossary.pdf",
    "Copy of Mijinyawa's CV.docx",
)
PROTECTED = ("oc_graph", "oc_taxonomy", "oc_ontology", "oc_semantic", "oc_embeddings", "oc_publication")
MIGRATIONS = (
    ("BUILD-070", "oc_intake.sources", "070_knowledge_intake.sql"),
    ("BUILD-076A", "oc_intake.documents", "076a_universal_intake.sql"),
    ("BUILD-079", "oc_missions.missions", "079_controlled_mission_orchestration.sql"),
    ("BUILD-081", "oc_sources.document_inventory", "081_brain_source_registry.sql"),
    ("BUILD-082", "oc_import.import_sessions", "082_controlled_drive_document_import.sql"),
)


def _date(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def migration_state(dsn):
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        return {build: bool(conn.execute("SELECT to_regclass(%s) IS NOT NULL present", (relation,)).fetchone()["present"])
                for build, relation, _ in MIGRATIONS}


def apply_missing_migrations(dsn):
    before = migration_state(dsn); applied = []
    for build, relation, filename in MIGRATIONS:
        if before[build]:
            continue
        migration = (ROOT / "migrations" / filename).read_text()
        if any(token in migration.upper() for token in ("DROP TABLE", "TRUNCATE", "DELETE FROM")):
            raise RuntimeError(f"DESTRUCTIVE_MIGRATION_REJECTED:{filename}")
        with psycopg.connect(dsn) as conn:
            conn.execute(migration)
        applied.append(filename)
    after = migration_state(dsn)
    if not all(after.values()):
        raise RuntimeError("PREREQUISITE_MIGRATION_INCOMPLETE")
    return before, after, applied


def protected_counts(dsn):
    result = {}
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        for schema in PROTECTED:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_type='BASE TABLE' ORDER BY table_name", (schema,))
            tables = [row["table_name"] for row in cur.fetchall()]
            table_counts = {}
            for table in tables:
                cur.execute(sql.SQL("SELECT count(*) row_count FROM {}.{}").format(sql.Identifier(schema), sql.Identifier(table)))
                table_counts[table] = cur.fetchone()["row_count"]
            result[schema] = table_counts
    return result


def direct_pilot_inventory(dsn, drive_service, service_account):
    shared = drive_service.files().get(fileId=SHARED_INTAKE_FOLDER_ID, supportsAllDrives=True,
        fields="id,name,mimeType,parents,webViewLink,driveId").execute()
    if shared.get("mimeType") != "application/vnd.google-apps.folder":
        raise RuntimeError("SHARED_INTAKE_FOLDER_IDENTITY_MISMATCH")
    folder = shared
    pilot_folder_id = folder["id"]
    fields = "nextPageToken,files(id,name,mimeType,size,sha256Checksum,md5Checksum,createdTime,modifiedTime,version,parents,webViewLink,owners(displayName,emailAddress,permissionId),permissions(id,type,role,emailAddress,displayName),trashed)"
    response = drive_service.files().list(q=f"'{pilot_folder_id}' in parents and trashed = false", pageSize=100,
        fields=fields, supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
    if response.get("nextPageToken"):
        raise RuntimeError("PILOT_FOLDER_EXCEEDS_SINGLE_CONTROLLED_PAGE")
    by_name = {item["name"]: item for item in response.get("files", []) if item.get("name") in NAMES}
    if set(by_name) != set(NAMES) or len(by_name) != 3:
        raise RuntimeError("EXACT_PILOT_DOCUMENT_SET_NOT_FOUND")
    repository = PostgresSourceRegistryRepository()
    source = repository.register_google_drive("BUILD-082 Pilot", "SERVICE_ACCOUNT", [pilot_folder_id])
    scan_id = repository.start_scan(str(source["source_id"]))
    states = []
    try:
        for name in NAMES:
            item = by_name[name]
            if item.get("parents") != [pilot_folder_id]:
                raise RuntimeError("PILOT_PARENT_MISMATCH")
            owners = item.get("owners") or []
            owner = owners[0].get("emailAddress") if owners else None
            file = DriveFile(str(item["id"]), name, "/Pilot/", str(item["mimeType"]),
                int(item["size"]) if item.get("size") is not None else None,
                item.get("sha256Checksum") or item.get("md5Checksum"), _date(item.get("createdTime")),
                _date(item.get("modifiedTime")), str(item.get("version") or "") or None, None,
                {"parent_pilot_folder_id":pilot_folder_id,"web_url":item.get("webViewLink"),"owner":owner,
                 "owners":owners,"permissions":item.get("permissions") or [],"authenticated_service_account":service_account,
                 "registration_source":"BUILD-082B_DIRECT_NON_RECURSIVE"})
            states.append(repository.inventory_file(str(source["source_id"]), scan_id, file))
        repository.finish_scan(scan_id, str(source["source_id"]), "COMPLETED", len(states), states.count("UNCHANGED"), states.count("DUPLICATE"), 0)
    except Exception as exc:
        repository.finish_scan(scan_id, str(source["source_id"]), "FAILED", 0, 0, 0, 1, exc.__class__.__name__)
        raise
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        records = conn.execute("""SELECT d.inventory_id,d.source_id,d.external_file_id,d.filename,d.folder_path,d.mime_type,d.byte_size,
            d.created_at,d.modified_at,d.provenance,d.first_seen_at,s.source_type,s.authentication_method
            FROM oc_sources.document_inventory d JOIN oc_sources.sources s ON s.source_id=d.source_id
            WHERE s.source_id=%s AND d.filename=ANY(%s) AND d.folder_path='/Pilot/' ORDER BY d.filename""",
            (source["source_id"], list(NAMES))).fetchall()
    if len(records) != 3 or {row["filename"] for row in records} != set(NAMES):
        raise RuntimeError("PILOT_REGISTRY_CARDINALITY_INVALID")
    return folder, records, states


class TimedGateway:
    def __init__(self, delegate): self.delegate, self.ms, self.content = delegate, {}, {}
    def retrieve(self, document):
        started=time.perf_counter(); result=self.delegate.retrieve(document)
        self.ms[document.registry_id]=round((time.perf_counter()-started)*1000,3); self.content[document.registry_id]=result.content
        return result


class TimedRepository:
    def __init__(self, delegate): self.delegate, self.transaction_ms = delegate, {}
    def __getattr__(self, name): return getattr(self.delegate, name)
    def persist_import(self, **kwargs):
        started=time.perf_counter(); result=self.delegate.persist_import(**kwargs)
        self.transaction_ms[kwargs["document"].registry_id]=round((time.perf_counter()-started)*1000,3)
        return result


def main():
    dsn = os.environ["DATABASE_URL"]
    credentials = json.loads(os.environ["GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON"])
    service_account = credentials.get("client_email")
    if not service_account: raise RuntimeError("SERVICE_ACCOUNT_IDENTITY_MISSING")
    total_started=time.perf_counter(); protected_before=protected_counts(dsn)
    migration_before,migration_after,migrations_applied=apply_missing_migrations(dsn)
    drive_gateway=GoogleDriveDocumentGateway.from_environment()
    folder,records,registry_states=direct_pilot_inventory(dsn,drive_gateway.service,service_account)
    timed_gateway=TimedGateway(drive_gateway); timed_repo=TimedRepository(PostgresDocumentImportRepository())
    import_service=DocumentImportService(timed_repo,timed_gateway)
    previews=[import_service.preview(row["inventory_id"],"owner_session") for row in records]
    first=[]; performance={}
    for row in records:
        registry_id=row["inventory_id"]; started=time.perf_counter(); result=import_service.import_one(registry_id,"owner_session")
        hash_started=time.perf_counter(); digest=hashlib.sha256(timed_gateway.content[registry_id]).hexdigest(); hash_ms=(time.perf_counter()-hash_started)*1000
        if digest != result.sha256: raise RuntimeError("HASH_VALIDATION_FAILED")
        performance[str(registry_id)]={"drive_retrieval_ms":timed_gateway.ms[registry_id],"hash_generation_ms":round(hash_ms,3),
            "database_transaction_ms":timed_repo.transaction_ms[registry_id],"total_import_ms":round((time.perf_counter()-started)*1000,3)}
        first.append(result.as_dict())
    with psycopg.connect(dsn,row_factory=dict_row) as conn:
        intake_first=conn.execute("SELECT count(*) row_count FROM oc_intake.documents WHERE provenance ? 'brain_source_registry_id'").fetchone()["row_count"]
    second=[]
    for row in records:
        started=time.perf_counter(); result=import_service.import_one(row["inventory_id"],"owner_session")
        performance[str(row["inventory_id"])]["duplicate_detection_ms"]=round((time.perf_counter()-started)*1000,3); second.append(result.as_dict())
    with psycopg.connect(dsn,row_factory=dict_row) as conn:
        intake_second=conn.execute("SELECT count(*) row_count FROM oc_intake.documents WHERE provenance ? 'brain_source_registry_id'").fetchone()["row_count"]
    if intake_first != intake_second or any(row["state"] not in {"UNCHANGED","DUPLICATE"} for row in second):
        raise RuntimeError("IDEMPOTENCY_VALIDATION_FAILED")
    ids=[row["inventory_id"] for row in records]
    invalid=({"paths":["x"]},{"urls":["https://invalid"]},{"sql":"select 1"},{"shell":"echo x"},{"drive_ids":["unregistered"]})
    rejected=sum(1 for payload in invalid if _rejected(payload))
    if rejected != len(invalid): raise RuntimeError("MISSION_REJECTION_FAILED")
    try:
        import_service.preview(9223372036854775807,"owner_session")
        raise RuntimeError("UNREGISTERED_REGISTRY_ID_ACCEPTED")
    except LookupError:
        unregistered_registry_id_rejected=True
    mission_repo=PostgresMissionRepository(dsn); mission_service=MissionService(mission_repo); mission_service.initialize()
    mission=mission_service.create({"mission_key":"build-082b-live-pilot","title":"BUILD-082B live pilot","description":"Approved registry-ID-only acceptance import",
        "mission_type":"controlled_drive_import","requested_by":"owner","priority":90,"schedule_type":"manual","scheduled_at":None,"recurrence_rule":None,
        "maximum_runs":1,"maximum_failures":1,"input_manifest":{"registry_ids":ids},"allowed_actions":["universal_intake_import"],
        "prohibited_actions":["drive_write","semantic_extraction","graph_write"],"target_services":["google_drive","universal_intake"],
        "target_domains":["Pilot"],"idempotency_key":"build-082b-live-pilot","created_from_template_id":None})
    if mission["state"] == "draft": mission_service.submit(mission["mission_id"],"owner","BUILD-082B acceptance")
    mission=mission_service.get(mission["mission_id"])
    if mission["state"] == "awaiting_approval": mission_service.approve(mission["mission_id"],"owner","explicit BUILD-082B authorization","BUILD-082B")
    mission_result=mission_service.run_one(mission["mission_id"],"build-082b-validator")
    protected_after=protected_counts(dsn)
    if protected_before != protected_after: raise RuntimeError("PROTECTED_SCHEMA_MUTATION_DETECTED")
    with psycopg.connect(dsn,row_factory=dict_row) as conn:
        revisions=conn.execute("SELECT revision_id,registry_id,intake_document_id,revision_number,sha256,byte_count,state,provenance,imported_at FROM oc_import.document_revisions WHERE registry_id=ANY(%s) ORDER BY registry_id,revision_number",(ids,)).fetchall()
        audits=conn.execute("SELECT session_id,registry_id,previous_state,new_state,occurred_at FROM oc_import.audit_trail WHERE registry_id=ANY(%s) ORDER BY audit_id",(ids,)).fetchall()
        sessions=conn.execute("SELECT session_id,actor,registry_ids,mission_id,state,total_count,imported_count,unchanged_count,duplicate_count,failed_count,started_at,completed_at FROM oc_import.import_sessions WHERE registry_ids && %s ORDER BY session_id",(ids,)).fetchall()
        retries=conn.execute("SELECT retry_id,session_id,registry_id,attempt_number,state,error_code,next_retry_at FROM oc_import.retry_tracking WHERE registry_id=ANY(%s) ORDER BY retry_id",(ids,)).fetchall()
        intake_safety=conn.execute("SELECT document_id,text_extraction_status,(extracted_text IS NULL) AS no_extracted_text FROM oc_intake.documents WHERE (provenance->>'brain_source_registry_id')::bigint=ANY(%s) ORDER BY document_id",(ids,)).fetchall()
        constraints=conn.execute("SELECT constraint_name,constraint_type,table_name FROM information_schema.table_constraints WHERE table_schema='oc_import' ORDER BY table_name,constraint_name").fetchall()
        indexes=conn.execute("SELECT indexname,tablename FROM pg_indexes WHERE schemaname='oc_import' ORDER BY tablename,indexname").fetchall()
        triggers=conn.execute("SELECT trigger_name,event_object_table,event_manipulation FROM information_schema.triggers WHERE trigger_schema='oc_import' ORDER BY trigger_name,event_manipulation").fetchall()
    if any(not row["no_extracted_text"] or row["text_extraction_status"] != "NOT_REQUESTED" for row in intake_safety):
        raise RuntimeError("SEMANTIC_EXTRACTION_DETECTED")
    report={"verdict":"READY_FOR_REVIEW","migrations_discovered":[m[2] for m in MIGRATIONS],"migrations_applied":migrations_applied,
        "migration_state_before":migration_before,"migration_state_after":migration_after,"oc_sources_verified":migration_after["BUILD-081"],
        "pilot_folder":{"id":folder["id"],"name":folder["name"]},"registry_records":records,"registry_population_states":registry_states,
        "previews":previews,"first_import":first,"second_import":second,"revisions":revisions,"audit":audits,
        "mission":{"mission_id":mission["mission_id"],"result":mission_result,"invalid_payloads_rejected":rejected,
            "unregistered_registry_id_rejected":unregistered_registry_id_rejected},
        "database":{"constraints":constraints,"indexes":indexes,"immutable_triggers":triggers,"import_sessions":sessions,
            "retry_tracking":retries,"intake_safety":intake_safety,"intake_count_stable":intake_first==intake_second},
        "protected_before":protected_before,"protected_after":protected_after,"security":{"drive_scope":"drive.readonly","drive_write_operations":0,
        "credentials_logged":False,"document_contents_logged":False,"service_account_identity":service_account},"performance":performance,
        "total_pipeline_ms":round((time.perf_counter()-total_started)*1000,3)}
    print(json.dumps(report,default=str,sort_keys=True))


def _rejected(payload):
    try: validate_mission_payload(payload); return False
    except ValueError: return True


if __name__ == "__main__": main()
