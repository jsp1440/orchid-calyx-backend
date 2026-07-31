from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.archive.routes import router


def test_archive_routes_are_registered():
    app = FastAPI()
    app.include_router(router)
    paths = {route.path for route in app.routes}
    assert {"/archive/import", "/archive/resume", "/archive/status", "/archive/statistics", "/archive/documents", "/archive/entities"} <= paths


def test_import_request_validation_rejects_empty_source():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    response = client.post("/archive/import", json={"source_path": ""})
    assert response.status_code in {401, 403, 422}
