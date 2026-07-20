from datetime import datetime, timezone
from types import SimpleNamespace

from app.document_import.bulk import BulkImportService
from app.document_import.models import ImportResult, ImportState


class Repo:
    def __init__(self): self.rows=[]; self.states={}; self.was_cancelled=False
    def candidates(self, source_id): return self.rows
    def source_id(self, run_id): return "s"
    def create_plan(self, source_id, actor, items): self.items=items; self.states={i["registry_id"]:"PENDING" for i in items}; return 7
    def start(self, run_id, actor):
        for item in self.items: self.states.setdefault(item["registry_id"],"PENDING")
    def pending(self, run_id): return [{"registry_id":i["registry_id"],"classification":i["classification"]} for i in self.items if self.states[i["registry_id"]]=="PENDING"]
    def cancelled(self, run_id): return self.was_cancelled
    def record(self, run_id, rid, state, error, result): self.states[rid]=state
    def finish(self, run_id, elapsed): return {"bulk_run_id":run_id,"states":self.states,"elapsed_ms":elapsed}
    def cancel(self, run_id, actor): self.was_cancelled=True; return {"state":"CANCELLED"}
    def history(self, limit): return [{"bulk_run_id":7}]


class Sources:
    def get_source(self, source_id): return {"source_type":"GOOGLE_DRIVE","configuration":{"folder_ids":["root"]}}


class Scanner:
    def scan(self, source_id, folders): return SimpleNamespace(discovered=5,duration_ms=1)


class Importer:
    def __init__(self, outcomes=None): self.calls=[]; self.outcomes=outcomes or {}; self.repository=self
    def actor_owns_source(self, actor, source_id): return True
    def import_one(self, rid, actor): self.calls.append(rid); return self.outcomes.get(rid,ImportResult(1,rid,ImportState.IMPORTED))


def row(rid, status="SCANNED", revision=None, modified=None, prior=None, mime="application/pdf"):
    return {"inventory_id":rid,"filename":f"f{rid}","folder_path":"/nested/","mime_type":mime,"status":status,
        "revision_id":revision,"modified_at":modified,"revision_modified_at":prior}


def test_preview_classifies_every_required_bucket_and_preserves_folder():
    repo=Repo(); now=datetime(2026,1,1,tzinfo=timezone.utc)
    repo.rows=[row(1),row(2,revision=2,modified=now,prior="old"),row(3,revision=3,modified=now,prior=now.isoformat()),
        row(4,status="DUPLICATE"),row(5,mime="image/png")]
    result=BulkImportService(repo,Scanner(),Sources(),Importer()).preview("s","owner")
    assert [x["classification"] for x in result["items"]]==["NEW","UPDATED","UNCHANGED","DUPLICATE","UNSUPPORTED"]
    assert result["items"][0]["folder"]=="/nested/" and result["counts_by_type"]["application/pdf"]==4


def test_execute_delegates_only_new_and_updated_to_build_082_and_continues_failures():
    repo=Repo(); repo.items=[{"registry_id":1,"classification":"NEW"},{"registry_id":2,"classification":"UPDATED"},
        {"registry_id":3,"classification":"UNCHANGED"},{"registry_id":4,"classification":"DUPLICATE"}]
    importer=Importer({2:ImportResult(1,2,ImportState.FAILED,error_code="boom")})
    result=BulkImportService(repo,Scanner(),Sources(),importer).execute(7,"owner")
    assert importer.calls==[1,2]
    assert result["states"]=={1:"IMPORTED",2:"FAILED",3:"SKIPPED",4:"DUPLICATE"}


def test_resume_uses_pending_only_and_cancel_stops_work():
    repo=Repo(); repo.items=[{"registry_id":1,"classification":"NEW"},{"registry_id":2,"classification":"NEW"}]; repo.states={1:"IMPORTED",2:"PENDING"}
    importer=Importer(); BulkImportService(repo,Scanner(),Sources(),importer).resume(7,"owner")
    assert importer.calls==[2]
    repo.states={1:"PENDING",2:"PENDING"}; repo.was_cancelled=True; importer.calls=[]
    BulkImportService(repo,Scanner(),Sources(),importer).execute(7,"owner"); assert importer.calls==[]


def test_migration_is_additive_and_protected_schemas_absent():
    sql=open("migrations/083_bulk_drive_brain_import.sql",encoding="utf-8").read().upper()
    assert "CREATE TABLE IF NOT EXISTS" in sql and "DROP " not in sql and "TRUNCATE" not in sql
    for protected in ("OC_GRAPH","OC_ONTOLOGY","OC_TAXONOMY","OC_SEMANTIC","OC_EMBEDDINGS","OC_PUBLICATION"): assert protected not in sql
