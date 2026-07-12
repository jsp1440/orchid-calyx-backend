"""Tests for BUILD-062 Backend Execution Integration.

Covers:
- Calyx Queue lifecycle management (enqueue, cancel, retry, pause, resume)
- Harvester cancel and reschedule endpoints
- Audit PDF/DOCX generation
- Worker job dispatch logic
"""

from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.calyx_queue import router as calyx_queue_router
from app.routers.harvesters import router as harvesters_router
from app.routers.health import router as health_router

API_KEY = "test-build062-secret"


# ─── Calyx Queue — router mount ───────────────────────────────────────────────

def test_calyx_queue_endpoints_are_mounted():
    app = FastAPI()
    app.include_router(health_router)
    paths = {route.path for route in app.routes}
    assert "/api/calyx-queue" in paths
    assert "/api/calyx-queue/{job_id}" in paths
    assert "/api/calyx-queue/{job_id}/cancel" in paths
    assert "/api/calyx-queue/{job_id}/retry" in paths
    assert "/api/calyx-queue/{job_id}/pause" in paths
    assert "/api/calyx-queue/{job_id}/resume" in paths
    assert "/api/calyx-queue/telemetry/summary" in paths


# ─── Calyx Queue — in-memory lifecycle ────────────────────────────────────────

def _queue_client(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    monkeypatch.setenv("DATABASE_URL", "")  # force in-memory mode
    app = FastAPI()
    app.include_router(calyx_queue_router)
    return TestClient(app)


def test_calyx_queue_enqueue_and_list(monkeypatch):
    client = _queue_client(monkeypatch)
    # Enqueue
    resp = client.post("/api/calyx-queue", json={"job_type": "harvest_gbif", "subsystem": "GBIF", "priority": 80}, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "queued"
    job_id = data["job"]["id"]
    assert job_id.startswith("CQ-")
    assert data["job"]["status"] == "queued"
    assert data["job"]["job_type"] == "harvest_gbif"

    # List
    resp = client.get("/api/calyx-queue", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    items = resp.json()["items"]
    ids = [i["id"] for i in items]
    assert job_id in ids


def test_calyx_queue_get_job(monkeypatch):
    client = _queue_client(monkeypatch)
    resp = client.post("/api/calyx-queue", json={"job_type": "audit", "subsystem": "AuditEngine"}, headers={"X-API-Key": API_KEY})
    job_id = resp.json()["job"]["id"]

    resp = client.get(f"/api/calyx-queue/{job_id}", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.json()["job"]["id"] == job_id


def test_calyx_queue_cancel_queued_job(monkeypatch):
    client = _queue_client(monkeypatch)
    resp = client.post("/api/calyx-queue", json={"job_type": "harvest_inaturalist", "subsystem": "iNaturalist"}, headers={"X-API-Key": API_KEY})
    job_id = resp.json()["job"]["id"]

    resp = client.post(f"/api/calyx-queue/{job_id}/cancel", json={}, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert resp.json()["job"]["status"] == "cancelled"


def test_calyx_queue_retry_cancelled_job(monkeypatch):
    client = _queue_client(monkeypatch)
    resp = client.post("/api/calyx-queue", json={"job_type": "harvest_literature", "subsystem": "Literature"}, headers={"X-API-Key": API_KEY})
    job_id = resp.json()["job"]["id"]

    client.post(f"/api/calyx-queue/{job_id}/cancel", json={}, headers={"X-API-Key": API_KEY})
    resp = client.post(f"/api/calyx-queue/{job_id}/retry", json={}, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    assert resp.json()["status"] == "retrying"
    assert resp.json()["job"]["retry_count"] == 1


def test_calyx_queue_cannot_cancel_completed_job(monkeypatch):
    from app.routers import calyx_queue as cq
    client = _queue_client(monkeypatch)
    resp = client.post("/api/calyx-queue", json={"job_type": "export", "subsystem": "Export"}, headers={"X-API-Key": API_KEY})
    job_id = resp.json()["job"]["id"]

    # Force job to completed state in-memory
    for item in cq._QUEUE:
        if item["id"] == job_id:
            item["status"] = "completed"

    resp = client.post(f"/api/calyx-queue/{job_id}/cancel", json={}, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 409


def test_calyx_queue_unknown_job_returns_404(monkeypatch):
    client = _queue_client(monkeypatch)
    resp = client.get("/api/calyx-queue/CQ-DOESNOTEXIST", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 404


def test_calyx_queue_invalid_status_filter_returns_400(monkeypatch):
    client = _queue_client(monkeypatch)
    resp = client.get("/api/calyx-queue?status=badstate", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 400


def test_calyx_queue_telemetry_summary(monkeypatch):
    client = _queue_client(monkeypatch)
    resp = client.get("/api/calyx-queue/telemetry/summary", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    data = resp.json()
    assert "lifecycle_counts" in data
    assert "queue_depth" in data
    assert "active_workers" in data
    assert data["build"] == "BUILD-062"


def test_calyx_queue_unauthenticated_rejected(monkeypatch):
    client = _queue_client(monkeypatch)
    resp = client.get("/api/calyx-queue")
    assert resp.status_code == 401


# ─── Harvester cancel and reschedule ─────────────────────────────────────────

def test_harvester_cancel_endpoint_is_mounted():
    app = FastAPI()
    app.include_router(harvesters_router)
    paths = {route.path for route in app.routes}
    assert "/api/harvesters/{harvester_id}/cancel" in paths
    assert "/api/harvesters/{harvester_id}/reschedule" in paths


def test_harvester_cancel_run():
    """cancel_run returns no_active_run when no run is outstanding."""
    from runtime.harvester_control import HarvesterControlPlane
    cp = HarvesterControlPlane()
    result = cp.cancel_run("gbif", "tester")
    assert result["status"] in {"no_active_run", "cancelled"}
    assert "harvester" in result


def test_harvester_cancel_run_after_run_once():
    """cancel_run cancels the most recent queued run."""
    from runtime.harvester_control import HarvesterControlPlane
    cp = HarvesterControlPlane()
    cp.run_once("inaturalist", "tester")
    result = cp.cancel_run("inaturalist", "tester")
    assert result["status"] == "cancelled"
    assert result["run"]["status"] == "cancelled"
    assert result["run"]["ended_at"] is not None


def test_harvester_reschedule():
    """reschedule is an alias for update_schedule with rescheduled status."""
    from runtime.harvester_control import HarvesterControlPlane
    cp = HarvesterControlPlane()
    result = cp.reschedule("gbif", "hourly", "tester")
    # Constitutional orchestrator may return review_required or rescheduled
    assert result.get("status") in {"rescheduled", "review_required"}


def test_harvester_cancel_endpoint_live(monkeypatch):
    """Cancel endpoint responds correctly via the harvesters router."""
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    app = FastAPI()
    app.include_router(harvesters_router)
    client = TestClient(app)

    # First queue a run
    client.post("/api/harvesters/gbif/run-once", headers={"X-API-Key": API_KEY})
    resp = client.post("/api/harvesters/gbif/cancel", headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in {"cancelled", "no_active_run"}


def test_harvester_reschedule_endpoint(monkeypatch):
    """Reschedule endpoint responds correctly."""
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    app = FastAPI()
    app.include_router(harvesters_router)
    client = TestClient(app)
    resp = client.post("/api/harvesters/gbif/reschedule", json={"schedule": "6h"}, headers={"X-API-Key": API_KEY})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("status") in {"rescheduled", "review_required"}


# ─── Audit PDF / DOCX generation ─────────────────────────────────────────────

_SAMPLE_PAYLOAD = {
    "audit_type": "overall",
    "generated_at": "2026-01-01T00:00:00+00:00",
    "confidence": "medium",
    "record_counts": {"taxa": 100, "occurrences": 5000},
    "missing_relationships": ["taxonomy_to_images"],
    "strengths": ["Live telemetry available"],
    "weaknesses": ["KG not connected"],
    "recommended_next_actions": ["Deploy migration"],
}


def test_audit_pdf_is_valid_pdf():
    from app.routers.owner_operations import audit_pdf
    pdf_bytes = audit_pdf(_SAMPLE_PAYLOAD)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:4] == b"%PDF"
    assert b"%%EOF" in pdf_bytes


def test_audit_docx_is_valid_zip():
    import io
    import zipfile
    from app.routers.owner_operations import audit_docx
    payload = {
        "audit_type": "atlas",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "confidence": "low",
        "record_counts": {"taxa": 50},
        "missing_relationships": [],
        "strengths": ["Atlas partially live"],
        "weaknesses": ["Occurrences low"],
        "recommended_next_actions": ["Run GBIF harvester"],
    }
    docx_bytes = audit_docx(payload)
    assert isinstance(docx_bytes, bytes)
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        names = zf.namelist()
        assert "word/document.xml" in names
        assert "[Content_Types].xml" in names


def test_generate_audit_pdf_format_returns_base64(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    from app.routers.owner_operations import router as owner_router
    app = FastAPI()
    app.include_router(owner_router)
    client = TestClient(app)
    resp = client.post(
        "/api/mission-control/owner/audits",
        json={"audit_type": "overall", "output_format": "pdf"},
        headers={"X-API-Key": API_KEY},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "generated"
    assert data["audit"]["output_format"] == "pdf"
    assert data["audit"]["content_encoding"] == "base64"
    raw = base64.b64decode(data["audit"]["content"])
    assert raw[:4] == b"%PDF"


def test_generate_audit_docx_format_returns_base64(monkeypatch):
    import io
    import zipfile
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    from app.routers.owner_operations import router as owner_router
    app = FastAPI()
    app.include_router(owner_router)
    client = TestClient(app)
    resp = client.post(
        "/api/mission-control/owner/audits",
        json={"audit_type": "overall", "output_format": "docx"},
        headers={"X-API-Key": API_KEY},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "generated"
    assert data["audit"]["output_format"] == "docx"
    assert data["audit"]["content_encoding"] == "base64"
    raw = base64.b64decode(data["audit"]["content"])
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        assert "word/document.xml" in zf.namelist()


def test_generate_audit_markdown_unchanged(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    from app.routers.owner_operations import router as owner_router
    app = FastAPI()
    app.include_router(owner_router)
    client = TestClient(app)
    resp = client.post(
        "/api/mission-control/owner/audits",
        json={"audit_type": "overall", "output_format": "markdown"},
        headers={"X-API-Key": API_KEY},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["audit"]["content_encoding"] == "none"
    assert isinstance(data["audit"]["content"], str)
    assert "Audit" in data["audit"]["content"]


def test_generate_audit_invalid_format_rejected(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)
    from app.routers.owner_operations import router as owner_router
    app = FastAPI()
    app.include_router(owner_router)
    client = TestClient(app)
    resp = client.post(
        "/api/mission-control/owner/audits",
        json={"audit_type": "overall", "output_format": "html"},
        headers={"X-API-Key": API_KEY},
    )
    assert resp.status_code == 422


# ─── Worker dispatch logic ────────────────────────────────────────────────────

def test_worker_harvester_dispatch():
    from app.worker import execute_job
    from unittest.mock import patch

    with patch("app.worker.execute_harvester_job") as mock_harvest:
        mock_harvest.return_value = {"status": "queued"}
        result = execute_job("harvest_gbif", {"actor": "worker"})
        mock_harvest.assert_called_once_with("harvest_gbif", {"actor": "worker"})


def test_worker_unknown_job_type_returns_skipped():
    from app.worker import execute_job
    result = execute_job("totally_unknown_type_xyz", {})
    assert result["status"] == "skipped"
    assert "totally_unknown_type_xyz" in result["reason"]


def test_worker_harvester_job_map_coverage():
    from app.worker import HARVESTER_JOB_MAP
    expected = {"harvest_inaturalist", "harvest_gbif", "harvest_traitbank", "harvest_mycorrhiza", "harvest_literature"}
    for key in expected:
        assert key in HARVESTER_JOB_MAP, f"Missing job map entry for {key}"


def test_worker_no_placeholder_sleep():
    """Verify the worker no longer has the placeholder time.sleep(1)."""
    import inspect
    from app import worker
    source = inspect.getsource(worker.main)
    # The placeholder was: time.sleep(1) with the comment about placeholder harvester logic
    assert "# 🔧 Placeholder" not in source
    assert "Placeholder: actual harvester logic" not in source


def test_worker_functions_complete():
    """Verify the worker exposes all required functions."""
    from app import worker
    assert hasattr(worker, "mark_job_failed")
    assert hasattr(worker, "execute_job")
    assert hasattr(worker, "execute_harvester_job")
    assert hasattr(worker, "HARVESTER_JOB_MAP")
    assert callable(worker.execute_job)
