"""Journey 15: ARK continuity state and backup/recovery evidence API tests.

Acceptance criteria:
- GET /api/ark/status returns 200 with a continuity_state field
- GET /api/ark/runs returns 200 with a list (empty in R1 stub)
- GET /api/ark/evidence/{run_id} for an unknown run_id returns 404
- ContinuityState enum has the required Journey 15 states
- ArkRunOutcome enum has SUCCESS and FAILED

These tests validate the owner-gated FastAPI routes added in app/ark/routes.py
and the Pydantic models in app/ark/models.py.  DB persistence and runner wiring
are a follow-up; this suite exercises the R1 MVP stub.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.ark.models import ArkRunOutcome, ContinuityState
from app.ark.routes import router
from app.security import verify_owner_or_api_key

OWNER = "test-owner"


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"subject": OWNER}
    return TestClient(app)


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


def test_get_ark_status_returns_200_with_continuity_state(client: TestClient) -> None:
    response = client.get("/api/ark/status")
    assert response.status_code == 200
    body = response.json()
    assert "continuity_state" in body


def test_get_ark_runs_returns_200_with_list(client: TestClient) -> None:
    response = client.get("/api/ark/runs")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)


def test_get_ark_evidence_unknown_run_returns_404(client: TestClient) -> None:
    response = client.get("/api/ark/evidence/nonexistent-run-id")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_continuity_state_enum_has_required_states() -> None:
    assert ContinuityState.DISCOVERED == "DISCOVERED"
    assert ContinuityState.RESTORE_TESTED == "RESTORE_TESTED"
    assert ContinuityState.RECOVERING == "RECOVERING"


def test_ark_run_outcome_enum_has_success_and_failed() -> None:
    assert ArkRunOutcome.SUCCESS == "SUCCESS"
    assert ArkRunOutcome.FAILED == "FAILED"
