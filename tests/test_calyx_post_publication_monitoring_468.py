from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import post_publication_monitoring as api
from app.security import verify_owner_or_api_key
from runtime.post_publication_monitoring import PostPublicationMonitoringService

OWNER = "monitor-owner"


def publication() -> dict[str, Any]:
    return {
        "publication_id": "pub-001",
        "assertion_id": "assertion-001",
        "ledger_id": "ledger-001",
        "ledger_revision_id": "ledger-rev-003",
        "ledger_hash": "ledger-sha-abc",
        "published_at": "2026-01-15T12:00:00Z",
        "approved_at": "2026-01-10T12:00:00Z",
        "approval_ttl_days": 180,
        "confidence": 0.9,
        "evidence": [
            {
                "evidence_id": "ev-1",
                "source_id": "source-1",
                "evidence_hash": "evidence-sha-1",
                "source_hash": "source-sha-1",
                "source_uri": "https://example.org/paper/1",
            },
            {
                "evidence_id": "ev-2",
                "source_id": "source-2",
                "evidence_hash": "evidence-sha-2",
                "source_hash": "source-sha-2",
                "source_uri": "https://example.org/paper/2",
            },
        ],
        "provenance": [{"publication_gate": "fixture", "review_state": "approved"}],
    }


def service(tmp_path: Path) -> PostPublicationMonitoringService:
    return PostPublicationMonitoringService(
        tmp_path / "monitoring",
        clock=lambda: datetime(2026, 8, 8, 12, 0, tzinfo=UTC),
    )


def seed(svc: PostPublicationMonitoringService) -> None:
    svc.register_publication(OWNER, publication())


def test_publication_baseline_is_immutable_and_replay_safe(tmp_path: Path):
    svc = service(tmp_path)
    first = svc.register_publication(OWNER, publication())
    second = svc.register_publication(OWNER, publication())
    assert first == second
    changed = publication()
    changed["confidence"] = 0.8
    try:
        svc.register_publication(OWNER, changed)
    except RuntimeError as exc:
        assert str(exc) == "MONITOR_IMMUTABLE_PUBLICATION_CONFLICT"
    else:
        raise AssertionError("published baseline must be immutable")


def test_changed_evidence_and_source_hash_create_review_tasks(tmp_path: Path):
    svc = service(tmp_path)
    seed(svc)
    result = svc.observe(
        OWNER,
        "pub-001",
        {
            "observed_at": "2026-03-01T12:00:00Z",
            "evidence": [{"evidence_id": "ev-1", "evidence_hash": "new-evidence", "source_hash": "new-source"}],
        },
    )
    reasons = {task["reason"] for task in result["review_tasks"]}
    assert reasons == {"evidence_hash_changed", "source_hash_changed"}
    assert result["production_graph_rewrite_performed"] is False


def test_retraction_supersession_and_withdrawal_are_distinct(tmp_path: Path):
    svc = service(tmp_path)
    seed(svc)
    retracted = svc.observe(OWNER, "pub-001", {"observed_at": "2026-03-01T12:00:00Z", "evidence": [{"evidence_id": "ev-1", "state": "retracted"}]})
    superseded = svc.observe(OWNER, "pub-001", {"observed_at": "2026-03-02T12:00:00Z", "evidence": [{"evidence_id": "ev-2", "state": "superseded"}]})
    withdrawn = svc.observe(OWNER, "pub-001", {"observed_at": "2026-03-03T12:00:00Z", "evidence": [{"evidence_id": "ev-2", "state": "withdrawn"}]})
    assert {task["reason"] for task in retracted["review_tasks"]} == {"evidence_retracted"}
    assert {task["reason"] for task in superseded["review_tasks"]} == {"evidence_superseded"}
    assert {task["reason"] for task in withdrawn["review_tasks"]} == {"evidence_withdrawn"}


def test_stale_approval_and_confidence_change_create_tasks(tmp_path: Path):
    svc = service(tmp_path)
    seed(svc)
    result = svc.observe(
        OWNER,
        "pub-001",
        {"observed_at": "2026-08-01T12:00:00Z", "confidence": 0.72, "evidence": []},
    )
    reasons = {task["reason"] for task in result["review_tasks"]}
    assert reasons == {"approval_stale", "confidence_changed"}


def test_review_task_creation_is_idempotent(tmp_path: Path):
    svc = service(tmp_path)
    seed(svc)
    observation = {"observed_at": "2026-03-01T12:00:00Z", "evidence": [{"evidence_id": "ev-1", "state": "retracted"}]}
    first = svc.observe(OWNER, "pub-001", observation)
    second = svc.observe(OWNER, "pub-001", observation)
    tasks = svc.review_tasks(OWNER, "pub-001")
    assert first["observation_id"] == second["observation_id"]
    assert first["review_task_ids"] == second["review_task_ids"]
    assert tasks["count"] == 1


def test_monitoring_status_exposes_lag_and_historical_state(tmp_path: Path):
    svc = service(tmp_path)
    seed(svc)
    svc.observe(OWNER, "pub-001", {"observed_at": "2026-08-07T12:00:00Z", "evidence": []})
    status = svc.status(OWNER, "pub-001")
    assert status["monitoring_lag_seconds"] == 86400.0
    assert status["observation_count"] == 1
    assert status["historical_record_preserved"] is True
    assert status["automatic_republication_authorized"] is False
    assert status["production_graph_rewrite_authorized"] is False
    assert status["scientific_approval_authorized"] is False


def test_unknown_evidence_fails_closed(tmp_path: Path):
    svc = service(tmp_path)
    seed(svc)
    try:
        svc.observe(OWNER, "pub-001", {"observed_at": "2026-03-01T12:00:00Z", "evidence": [{"evidence_id": "ev-missing"}]})
    except ValueError as exc:
        assert str(exc) == "MONITOR_UNKNOWN_EVIDENCE_ID:ev-missing"
    else:
        raise AssertionError("unknown evidence must not be silently accepted")


def test_protected_api_round_trip(tmp_path: Path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setattr(api, "_service", lambda: svc)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": OWNER, "auth_type": "test"}
    client = TestClient(app)

    created = client.put("/brain/mission-control/publication-monitoring/publications/pub-001", json=publication())
    assert created.status_code == 200
    observed = client.post(
        "/brain/mission-control/publication-monitoring/publications/pub-001/observe",
        json={"observed_at": "2026-03-01T12:00:00Z", "evidence": [{"evidence_id": "ev-1", "state": "retracted"}]},
    )
    assert observed.status_code == 200
    assert observed.json()["review_task_ids"]
    tasks = client.get("/brain/mission-control/publication-monitoring/publications/pub-001/tasks")
    assert tasks.status_code == 200
    assert tasks.json()["count"] == 1
    status = client.get("/brain/mission-control/publication-monitoring/publications/pub-001/status")
    assert status.status_code == 200
    assert status.json()["decision"] == "REVIEW_REQUIRED"
