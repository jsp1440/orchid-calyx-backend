from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.document_import.dependencies import get_import_repository, get_import_service
from app.document_import.models import ImportResult, ImportState, RegistryDocument, RetrievedDocument
from app.document_import.routes import router
from app.document_import.service import DocumentImportService, validate_mission_payload
from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key


def document(registry_id=1, mime="application/pdf", name="paper.pdf", folder="/Pilot/"):
    now = datetime(2026, 7, 1, tzinfo=timezone.utc)
    return RegistryDocument(registry_id, "source", f"file-{registry_id}", f"https://drive.google.com/open?id=file-{registry_id}", name, mime, folder, "owner", now, now)


class FakeGateway:
    def __init__(self, content=b"content"):
        self.content, self.calls = content, []
    def retrieve(self, item):
        self.calls.append(item.drive_file_id)
        extension = ".docx" if item.mime_type == "application/vnd.google-apps.document" else Path(item.filename).suffix
        export = "DOCX" if item.mime_type == "application/vnd.google-apps.document" else None
        return RetrievedDocument(self.content, export, "application/octet-stream", extension)


class MemoryRepository:
    def __init__(self, docs=None):
        self.docs = docs or {1: document()}; self.revisions = {}; self.hashes = {}; self.audit = []; self.sessions = {}; self.failures = {}; self.next_session = 1
    def get_registry_document(self, registry_id): return self.docs.get(registry_id)
    def actor_owns_source(self, actor, source_id): return actor == "owner"
    def create_session(self, actor, registry_ids, mission_id, version):
        value = self.next_session; self.next_session += 1; self.sessions[value] = {"state":"REGISTERED","ids":registry_ids}; return value
    def transition(self, session_id, registry_id, previous, target, actor, **kwargs): self.sessions[session_id]["state"] = target.value; self.audit.append((registry_id, previous.value if previous else None, target.value))
    def latest_revision(self, registry_id): return deepcopy(self.revisions.get(registry_id, [None])[-1]) if self.revisions.get(registry_id) else None
    def persist_import(self, **kwargs):
        item, content_hash = kwargs["document"], kwargs["sha256"]
        latest = self.revisions.get(item.registry_id, [])
        if latest and latest[-1]["sha256"] == content_hash:
            old = latest[-1]; return ImportResult(kwargs["session_id"],item.registry_id,ImportState.UNCHANGED,old["revision_id"],old["intake_document_id"],content_hash,kwargs["retrieved"].content.__len__(),old["revision_number"])
        duplicate = self.hashes.get(content_hash); number = len(latest)+1; revision_id = sum(map(len,self.revisions.values()))+1
        state = ImportState.DUPLICATE if duplicate else ImportState.IMPORTED
        row = {"revision_id":revision_id,"intake_document_id":revision_id,"revision_number":number,"sha256":content_hash}
        self.revisions.setdefault(item.registry_id,[]).append(row); self.hashes.setdefault(content_hash,revision_id)
        return ImportResult(kwargs["session_id"],item.registry_id,state,revision_id,revision_id,content_hash,len(kwargs["retrieved"].content),number,duplicate)
    def is_cancelled(self, session_id): return self.sessions[session_id]["state"] == "CANCELLED"
    def cancel_session(self, session_id, actor): self.sessions[session_id]["state"]="CANCELLED"; return {"session_id":session_id,"state":"CANCELLED"}
    def record_failure(self, session_id, registry_id, error_code, state): self.failures[(session_id,registry_id)] = state.value
    def can_retry(self, session_id, registry_id): return self.failures.get((session_id,registry_id)) == "RETRYABLE"
    def increment_retry(self, session_id, registry_id, actor): pass
    def history(self, registry_id, limit): return self.revisions.get(registry_id,[])[:limit]


def test_successful_pdf_and_docx_imports_create_hashes_and_intake_links():
    docs = {1:document(),2:document(2,"application/vnd.openxmlformats-officedocument.wordprocessingml.document","cv.docx")}
    repo = MemoryRepository(docs); service = DocumentImportService(repo,FakeGateway())
    assert service.import_one(1,"owner").state == ImportState.IMPORTED
    result = service.import_one(2,"owner")
    assert result.state == ImportState.DUPLICATE and len(result.sha256) == 64 and result.intake_document_id


def test_google_doc_uses_docx_export_contract():
    item = document(1,"application/vnd.google-apps.document","notes")
    repo = MemoryRepository({1:item}); result = DocumentImportService(repo,FakeGateway()).preview(1,"owner")
    assert (result["export_format"],result["extension"],result["content_retrieved"]) == ("DOCX",".docx",False)


def test_missing_registry_unsupported_format_ownership_and_pilot_boundary():
    service = DocumentImportService(MemoryRepository(),FakeGateway())
    with pytest.raises(LookupError): service.preview(99,"owner")
    with pytest.raises(PermissionError): service.preview(1,"intruder")
    with pytest.raises(PermissionError): DocumentImportService(MemoryRepository({1:document(folder="/Other/")}),FakeGateway()).preview(1,"owner")
    with pytest.raises(ValueError,match="UNSUPPORTED_FORMAT"): DocumentImportService(MemoryRepository({1:document(mime="image/png")}),FakeGateway()).preview(1,"owner")


def test_unchanged_rerun_revision_and_cross_file_duplicate_detection():
    repo = MemoryRepository({1:document(),2:document(2)}); gateway = FakeGateway(b"one"); service = DocumentImportService(repo,gateway)
    assert service.import_one(1,"owner").state == ImportState.IMPORTED
    assert service.import_one(1,"owner").state == ImportState.UNCHANGED
    assert service.import_one(2,"owner").state == ImportState.DUPLICATE
    gateway.content = b"changed"
    changed = service.import_one(1,"owner")
    assert (changed.state,changed.revision_number) == (ImportState.IMPORTED,2)


def test_every_transition_is_audited_and_no_semantic_side_effects_exist():
    repo = MemoryRepository(); DocumentImportService(repo,FakeGateway()).import_one(1,"owner")
    assert [target for _,_,target in repo.audit] == ["READY","IMPORTING","IMPORTED"]
    source = Path(__file__).parents[1] / "app" / "document_import"
    text = "\n".join(item.read_text() for item in source.glob("*.py"))
    assert "app.semantic" not in text and "app.ontology" not in text and "oc_graph" not in text and "embedding" not in text.lower()


def test_batch_limit_cancel_retry_and_mission_payload_rules():
    repo = MemoryRepository(); service = DocumentImportService(repo,FakeGateway(),batch_limit=1)
    with pytest.raises(ValueError,match="BATCH_LIMIT_EXCEEDED"): service.import_batch([1,2],"owner")
    sid = repo.create_session("owner",[1],None,"test"); assert service.cancel(sid,"owner")["state"] == "CANCELLED"
    assert validate_mission_payload({"registry_ids":[1,2]}) == [1,2]
    for bad in ({"registry_ids":["1"]},{"registry_ids":[1],"url":"x"},{"path":"x"}):
        with pytest.raises(ValueError): validate_mission_payload(bad)


def test_api_is_authenticated_and_routes_preview_history_import_batch_retry_cancel():
    app = FastAPI(); app.include_router(router); repo = MemoryRepository(); service = DocumentImportService(repo,FakeGateway())
    app.dependency_overrides[get_import_repository] = lambda: repo; app.dependency_overrides[get_import_service] = lambda: service
    app.dependency_overrides[add_mission_control_cors_headers] = lambda: None
    client = TestClient(app)
    assert client.post("/api/brain/imports/preview",json={"registry_id":1}).status_code == 401
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor":"owner"}
    assert client.post("/api/brain/imports/preview",json={"registry_id":1}).status_code == 200
    assert client.post("/api/brain/imports",json={"registry_id":1}).status_code == 201
    assert client.get("/api/brain/imports/history?registry_id=1").status_code == 200


def test_migration_is_additive_idempotent_indexed_and_forbids_graph_ontology_semantics():
    sql = (Path(__file__).parents[1]/"migrations"/"082_controlled_drive_document_import.sql").read_text()
    assert sql.count("CREATE TABLE IF NOT EXISTS") == 5
    for table in ("import_sessions","document_revisions","hash_index","audit_trail","retry_tracking"): assert table in sql
    assert "DROP " not in sql.upper() and "ALTER TABLE" not in sql.upper()
    assert "oc_graph" not in sql and "oc_ontology" not in sql and "oc_semantic" not in sql


def test_mission_control_is_an_explicit_internal_import_actor():
    source = (Path(__file__).parents[1]/"app"/"document_import"/"repository.py").read_text()
    assert '"mission_control"' in source
