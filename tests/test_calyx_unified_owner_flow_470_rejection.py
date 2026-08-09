from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers import calyx_unified_owner_flow as flow
from app.routers.calyx_core import router as calyx_core_router
from app.security import verify_owner_or_api_key


class FakeDb:
    def rollback(self):
        return None


def test_gate_rejection_is_never_reported_as_published(monkeypatch):
    app = FastAPI()
    app.include_router(calyx_core_router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"subject": "owner-a"}
    app.dependency_overrides[get_db] = lambda: FakeDb()

    mission = {
        "mission_id": "mission-laelia",
        "tenant_id": "owner-a",
        "project_id": "laelia-anceps-demonstration",
        "reasoning_ledger": {"ledger_id": "ledger-laelia", "version": 4},
    }
    candidate = {
        "ledger_id": "ledger-laelia",
        "version": 5,
        "review_content_hash": "a" * 64,
    }
    monkeypatch.setattr(flow, "_mission_for_owner", lambda mission_id, owner: mission)
    monkeypatch.setattr(
        flow,
        "discover_eligible_ledgers",
        lambda db, owner: {
            "result": "ELIGIBLE_LEDGER_FOUND",
            "eligible_ledgers": [candidate],
        },
    )

    class FakeGate:
        @classmethod
        def from_environment(cls):
            return object()

    class RejectedPublication:
        def __init__(self, db, gate):
            pass

        def publish(self, *args, **kwargs):
            return (
                {
                    "publication_status": "rejected",
                    "canonical_publication_id": None,
                    "failure_reason": "governed gate rejected artifact",
                    "publication_gate_result": None,
                },
                True,
            )

    monkeypatch.setattr(flow, "ExistingKnowledgeGraphPublicationGate", FakeGate)
    monkeypatch.setattr(flow, "ReasoningLedgerPublicationService", RejectedPublication)

    response = TestClient(app).post(
        "/api/mission-control/calyx-owner-flow/mission-laelia/publish",
        json={"explicit_owner_confirmation": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "PUBLICATION_REJECTED"
    assert body["publication_status"] == "rejected"
    assert body["graph_version"] is None
    assert body["duplicate_replay_no_op"] is False
    assert "rejected" in body["plain_language_status"].lower()
    assert "published" not in body["plain_language_status"].lower()
