from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.source_registry.dependencies import get_scan_service, get_source_repository
from app.source_registry.drive import walk_drive
from app.source_registry.models import DriveFile
from app.source_registry.routes import router
from app.source_registry.service import SourceScanService


class FakeDrive:
    def __init__(self):
        self.calls = []
        self.tree = {
            "root": [{"id":"folder","name":"Research","mimeType":"application/vnd.google-apps.folder"}, {"id":"a","name":"paper.pdf","mimeType":"application/pdf","size":"42","md5Checksum":"sum","createdTime":"2026-01-01T00:00:00Z","modifiedTime":"2026-01-02T00:00:00Z"}],
            "folder": [{"id":"b","name":"Notes","mimeType":"application/vnd.google-apps.document","createdTime":"2026-01-01T00:00:00Z","modifiedTime":"2026-01-03T00:00:00Z","version":"2"}],
        }

    def children(self, folder_id):
        self.calls.append(folder_id)
        return deepcopy(self.tree.get(folder_id, []))


class MemoryRepository:
    def __init__(self):
        self.source = {"source_id":"source-1","source_name":"Drive","source_type":"GOOGLE_DRIVE","authentication_method":"SERVICE_ACCOUNT","status":"ACTIVE","last_scan":None,"total_documents":0,"total_processed":0,"total_failed":0,"configuration":{"folder_ids":["root"]}}
        self.inventory = {}
        self.logs = []

    def register_google_drive(self, name, authentication_method, folder_ids):
        self.source.update(source_name=name, authentication_method=authentication_method, configuration={"folder_ids":folder_ids})
        return deepcopy(self.source)

    def list_sources(self): return [deepcopy(self.source)]
    def get_source(self, source_id): return deepcopy(self.source) if source_id == "source-1" else None
    def start_scan(self, source_id):
        self.logs.append({"scan_id":len(self.logs)+1,"source_id":source_id,"status":"RUNNING"})
        return len(self.logs)
    def inventory_file(self, source_id, scan_id, file):
        old = self.inventory.get(file.file_id)
        if old and (old.modified_at,old.checksum,old.filename,old.folder_path) == (file.modified_at,file.checksum,file.filename,file.folder_path): return "UNCHANGED"
        duplicate = next((value for value in self.inventory.values() if value.file_id != file.file_id and ((file.checksum and value.checksum == file.checksum) or (not file.checksum and file.native_duplicate_key and value.native_duplicate_key == file.native_duplicate_key))), None)
        self.inventory[file.file_id] = file
        return "DUPLICATE" if duplicate else ("CHANGED" if old else "SCANNED")
    def finish_scan(self, scan_id, source_id, status, processed, unchanged, duplicates, failed, error=None):
        self.logs[scan_id-1].update(status=status, documents_processed=processed, documents_unchanged=unchanged, duplicates_found=duplicates, documents_failed=failed, error_message=error)
        self.source["total_documents"] = len(self.inventory)
        self.source["last_scan"] = datetime.now(timezone.utc)
    def scan_logs(self, source_id, limit): return deepcopy(self.logs[-limit:])
    def dashboard(self):
        return {"total_sources":1,"total_documents":len(self.inventory),"documents_processed":0,"duplicates":0,"failed_files":0,"last_scan_time":self.source["last_scan"],"processing_queue":len(self.inventory)}


def test_recursive_metadata_walk_never_requests_content():
    drive = FakeDrive()
    files = list(walk_drive(drive, ["root"]))
    assert drive.calls == ["root", "folder"]
    assert [(f.file_id, f.folder_path) for f in files] == [("a", "/"), ("b", "/Research/")]
    assert files[0].checksum == "sum"
    assert files[1].native_duplicate_key


def test_incremental_scan_skips_unchanged_and_marks_renamed_checksum_duplicate():
    repository, drive = MemoryRepository(), FakeDrive()
    service = SourceScanService(repository, drive)
    first = service.scan("source-1", ["root"])
    second = service.scan("source-1", ["root"])
    assert (first.processed, second.processed, second.unchanged) == (2, 0, 2)
    drive.tree["root"].append({"id":"copy","name":"renamed.pdf","mimeType":"application/pdf","size":"42","md5Checksum":"sum","modifiedTime":"2026-01-04T00:00:00Z"})
    third = service.scan("source-1", ["root"])
    assert third.duplicates == 1


def test_scan_failure_is_logged():
    class BrokenDrive:
        def children(self, folder_id): raise RuntimeError("drive unavailable")
    repository = MemoryRepository()
    try:
        SourceScanService(repository, BrokenDrive()).scan("source-1", ["root"])
    except RuntimeError:
        pass
    assert repository.logs[-1]["status"] == "FAILED"
    assert "drive unavailable" in repository.logs[-1]["error_message"]


def test_protected_api_integration_and_dashboard_contract():
    repository, drive = MemoryRepository(), FakeDrive()
    app = FastAPI(); app.include_router(router)
    app.dependency_overrides[get_source_repository] = lambda: repository
    app.dependency_overrides[get_scan_service] = lambda: SourceScanService(repository, drive)
    from app.security import verify_owner_or_api_key
    from app.routers.health import add_mission_control_cors_headers
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor":"test"}
    app.dependency_overrides[add_mission_control_cors_headers] = lambda: None
    client = TestClient(app)
    response = client.post("/api/brain/sources/source-1/scan")
    assert response.status_code == 200
    assert response.json()["metadata_only"] is True
    dashboard = client.get("/api/brain/sources/dashboard/summary").json()
    assert set(dashboard) == {"total_sources","total_documents","documents_processed","duplicates","failed_files","last_scan_time","processing_queue"}


def test_migration_defines_inventory_statuses_and_no_graph_tables():
    sql = (Path(__file__).parents[1] / "migrations" / "081_brain_source_registry.sql").read_text()
    for status in ("NEW","SCANNED","PROCESSED","FAILED","DUPLICATE","CHANGED"):
        assert f"'{status}'" in sql
    assert "oc_graph" not in sql
