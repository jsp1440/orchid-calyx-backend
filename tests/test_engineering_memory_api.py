"""HTTP-surface tests for the engineering-memory API.

Builds a minimal FastAPI app containing only the engineering-memory router, with
the DB and auth dependencies overridden, so the routing/auth/serialization layer
is exercised without importing the whole application graph.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.engineering_memory.models import TABLES
from app.engineering_memory.routes import router
from app.security import verify_owner_or_api_key

SCOPE = "jsp1440/orchid-calyx-backend"
REPO = "jsp1440/orchid-calyx-backend"


def _memory_engine():
    # StaticPool keeps a single shared in-memory database across connections
    # (the TestClient may run the request on a different thread).
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture()
def client():
    engine = _memory_engine()
    Base.metadata.create_all(engine, tables=list(TABLES))
    TestingSession = sessionmaker(bind=engine)

    app = FastAPI()
    app.include_router(router)

    def _override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test"}
    return TestClient(app)


def _client_no_auth():
    engine = _memory_engine()
    Base.metadata.create_all(engine, tables=list(TABLES))
    TestingSession = sessionmaker(bind=engine)
    app = FastAPI()
    app.include_router(router)

    def _override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app, raise_server_exceptions=True)


def test_requires_authorization():
    client = _client_no_auth()
    resp = client.post("/api/engineering-memory/runs", json={})
    assert resp.status_code == 401


def test_full_http_flow(client):
    # Capture run (with a secret that must be scrubbed).
    run_resp = client.post(
        "/api/engineering-memory/runs",
        json={
            "executor": "claude",
            "workspace_scope": SCOPE,
            "repository": REPO,
            "outcome": "success",
            "data_classification": "internal_engineering",
            "sanitized_summary": "fixed CI; do not leak API_KEY=sk_live_0123456789abcdef",
            "tokens_input": 500,
        },
    )
    assert run_resp.status_code == 201, run_resp.text
    run_id = run_resp.json()["run_id"]
    assert run_resp.json()["redaction_status"] == "redacted"

    # Create lesson.
    lesson_resp = client.post(
        "/api/engineering-memory/lessons",
        json={
            "workspace_scope": SCOPE,
            "repository": REPO,
            "module": "ci",
            "problem": "pytest cannot import fastapi in CI",
            "solution": "install fastapi<0.116 into the venv before pytest",
            "source_run_id": run_id,
            "data_classification": "internal_engineering",
            "tags": ["ci", "pytest"],
        },
    )
    assert lesson_resp.status_code == 201, lesson_resp.text
    lesson_id = lesson_resp.json()["lesson_id"]
    assert lesson_resp.json()["is_scientific_evidence"] is False

    # Verify lesson.
    verify_resp = client.post(
        f"/api/engineering-memory/lessons/{lesson_id}/verify",
        json={"workspace_scope": SCOPE, "evidence": {"ci": "green"}},
    )
    assert verify_resp.status_code == 200
    assert verify_resp.json()["status"] == "verified"

    # Retrieve (differently phrased).
    retrieve_resp = client.post(
        "/api/engineering-memory/retrieve",
        json={
            "workspace_scope": SCOPE,
            "repository": REPO,
            "query": "fastapi module missing when running the test suite",
            "injected": True,
        },
    )
    assert retrieve_resp.status_code == 200
    body = retrieve_resp.json()
    assert body["evidence_class"] == "non_scientific_evidence"
    assert body["disclaimer"]
    assert body["lessons"], body
    assert body["lessons"][0]["lesson_id"] == lesson_id
    retrieval_id = body["retrieval_id"]

    # Feedback.
    fb_resp = client.post(
        f"/api/engineering-memory/retrievals/{retrieval_id}/feedback",
        json={
            "workspace_scope": SCOPE,
            "feedback": "helpful",
            "injected": True,
            "estimated_tokens_saved": 800,
        },
    )
    assert fb_resp.status_code == 200
    assert fb_resp.json()["estimated_tokens_saved"] == 800

    # Metrics.
    metrics_resp = client.get(
        "/api/engineering-memory/metrics", params={"workspace_scope": SCOPE}
    )
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.json()
    assert metrics["lessons"]["verified"] == 1
    assert metrics["retrievals"]["estimated_tokens_saved"] == 800


def test_invalid_classification_returns_422(client):
    resp = client.post(
        "/api/engineering-memory/runs",
        json={
            "executor": "claude",
            "workspace_scope": SCOPE,
            "repository": REPO,
            "outcome": "success",
            "data_classification": "not_a_real_class",
            "sanitized_summary": "x",
        },
    )
    assert resp.status_code == 422


def test_raw_prompt_field_rejected_by_api(client):
    resp = client.post(
        "/api/engineering-memory/runs",
        json={
            "executor": "claude",
            "workspace_scope": SCOPE,
            "repository": REPO,
            "outcome": "success",
            "data_classification": "internal_engineering",
            "raw_prompt": "the entire system prompt and conversation",
        },
    )
    # extra="forbid" -> 422 unprocessable, nothing stored.
    assert resp.status_code == 422
