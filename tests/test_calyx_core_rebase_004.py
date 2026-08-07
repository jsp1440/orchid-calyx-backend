from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers import calyx_operator_workflow as operator
from app.routers.calyx_core import router as calyx_core_router
from app.security import verify_owner_or_api_key


class FakeDb:
    def rollback(self):
        return None


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(calyx_core_router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"subject": "owner-a"}
    app.dependency_overrides[get_db] = lambda: FakeDb()
    return TestClient(app)


def test_operator_routes_are_mounted_through_current_calyx_core_router():
    paths = {route.path for route in calyx_core_router.routes}
    assert "/api/mission-control/calyx-operator/missions" in paths
    assert "/api/mission-control/calyx-operator/ledgers/eligible" in paths
    assert "/api/mission-control/calyx-operator/publications" in paths
    assert "/api/mission-control/calyx-operator/panel" in paths


def test_start_mission_derives_tenant_and_actor_from_auth(monkeypatch):
    captured = {}

    def fake_start(**kwargs):
        captured.update(kwargs)
        return {
            "mission_id": "m1",
            "question": kwargs["question"],
            "tenant_id": kwargs["tenant_id"],
            "project_id": kwargs["project_id"],
            "state": "AWAITING_HUMAN_REVIEW",
            "current_stage": "eligible_for_publication_state",
            "steps_executed": 9,
            "sources": [],
            "supporting_evidence": [],
            "contradicting_evidence": [],
            "missing_evidence": [],
            "confidence": 0.8,
            "blockers": [],
            "validation": {"valid": True, "blockers": []},
            "review_status": "HUMAN_REVIEW_REQUIRED",
            "publication_eligibility": {"eligible": False, "automatic_publication": False, "blockers": ["HUMAN_REVIEW_REQUIRED"]},
            "reasoning_ledger": {"ledger_id": "ledger-1", "version": 1},
            "created_at": "now",
            "updated_at": "now",
        }

    monkeypatch.setattr(operator.BRAIN_MISSION_SERVICE, "start", fake_start)
    response = _client().post(
        "/api/mission-control/calyx-operator/missions",
        json={"question": "What evidence supports this orchid relationship?", "project_id": "project-1"},
    )
    assert response.status_code == 201
    assert captured["tenant_id"] == "owner-a"
    assert captured["actor"] == "owner-a"
    assert response.json()["automatic_publication"] is False


def test_cross_tenant_mission_is_hidden(monkeypatch):
    monkeypatch.setattr(
        operator.BRAIN_MISSION_SERVICE,
        "status",
        lambda mission_id: {
            "mission_id": mission_id,
            "tenant_id": "owner-b",
            "project_id": "project-1",
            "question": "private mission",
        },
    )
    response = _client().get("/api/mission-control/calyx-operator/missions/m1")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "MISSION_NOT_FOUND"


def test_review_identity_comes_from_authenticated_owner(monkeypatch):
    captured = {}

    class FakeLedgerService:
        def __init__(self, db):
            pass

        def review(self, ledger_id, decision, *, owner, expected_version):
            captured.update(
                ledger_id=ledger_id,
                reviewer=decision.reviewer,
                outcome=decision.outcome.value,
                owner=owner,
                expected_version=expected_version,
            )
            return object()

    monkeypatch.setattr(operator, "OperationalReasoningLedgerService", FakeLedgerService)
    monkeypatch.setattr(operator, "ledger_to_dict", lambda ledger: {"ledger_id": "ledger-1", "version": 2})
    response = _client().post(
        "/api/mission-control/calyx-operator/ledgers/ledger-1/review",
        json={"expected_version": 1, "outcome": "approved", "rationale": "Evidence and provenance reviewed."},
    )
    assert response.status_code == 200
    assert captured["reviewer"] == "owner-a"
    assert captured["owner"] == "owner-a"
    assert response.json()["publication_invoked"] is False


def test_publication_confirmation_fails_before_publication_service(monkeypatch):
    called = {"publication": 0}

    class ForbiddenPublicationService:
        def __init__(self, *args, **kwargs):
            called["publication"] += 1
            raise AssertionError("publication service must not be constructed")

    monkeypatch.setattr(operator, "ReasoningLedgerPublicationService", ForbiddenPublicationService)
    response = _client().post(
        "/api/mission-control/calyx-operator/publications",
        json={
            "ledger_id": "ledger-1",
            "expected_version": 1,
            "expected_review_content_hash": "a" * 64,
            "explicit_owner_confirmation": False,
            "publication_note": "do not publish",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "EXPLICIT_OWNER_CONFIRMATION_REQUIRED"
    assert called["publication"] == 0


def test_eligible_discovery_uses_shared_owner_scoped_service(monkeypatch):
    captured = {}

    def fake_discovery(db, owner):
        captured["owner"] = owner
        return {
            "contract": "calyx-eligible-reasoning-ledger-discovery-v1",
            "eligible_count": 0,
            "eligible_ledgers": [],
            "read_only": True,
            "production_mutation": False,
            "publication_endpoint_invoked": False,
        }

    monkeypatch.setattr(operator, "discover_eligible_ledgers", fake_discovery)
    response = _client().get("/api/mission-control/calyx-operator/ledgers/eligible")
    assert response.status_code == 200
    assert captured["owner"] == "owner-a"
    assert response.json()["publication_endpoint_invoked"] is False


def test_graph_version_endpoint_does_not_invent_version(monkeypatch):
    monkeypatch.setattr(
        operator,
        "build_calyx_core_certification",
        lambda: {"overall_status": "partial_operational_readiness", "operational_blockers": {"occurrences": ["durable persistence missing"]}},
    )
    response = _client().get("/api/mission-control/calyx-operator/graph/version")
    assert response.status_code == 200
    payload = response.json()
    assert payload["graph_version"] is None
    assert payload["version_state"] == "NOT_ASSERTED_BY_OPERATOR_FACADE"
    assert payload["production_graph_mutation"] is False
