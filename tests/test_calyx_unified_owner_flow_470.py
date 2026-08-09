from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers import calyx_unified_owner_flow as flow
from app.routers.calyx_core import router as calyx_core_router
from app.security import verify_owner_or_api_key

PROJECT_ID = "11111111-1111-4111-8111-111111111111"


class FakeDb:
    def rollback(self):
        return None


def client() -> TestClient:
    app = FastAPI()
    app.include_router(calyx_core_router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"subject": "owner-a"}
    app.dependency_overrides[get_db] = lambda: FakeDb()
    return TestClient(app)


def mission(*, review_status: str = "HUMAN_REVIEW_REQUIRED"):
    return {
        "mission_id": "mission-laelia",
        "question": flow.LAELIA_ANCEPS_QUESTION,
        "tenant_id": "owner-a",
        "project_id": PROJECT_ID,
        "state": "AWAITING_HUMAN_REVIEW",
        "current_stage": "eligible_for_publication_state",
        "steps_executed": 9,
        "plan": {"domains": ["taxonomy", "distribution", "pollination", "conservation", "mycorrhiza"]},
        "sources": [{"source_id": "source-1", "title": "Fixture evidence"}],
        "supporting_evidence": [{"source_id": "source-1"}],
        "contradicting_evidence": [{"source_id": "source-2"}],
        "missing_evidence": ["recent mycorrhizal field evidence"],
        "confidence": 0.78,
        "blockers": [],
        "validation": {"valid": True, "blockers": []},
        "review_status": review_status,
        "publication_eligibility": {"eligible": False, "automatic_publication": False},
        "reasoning_ledger": {"ledger_id": "ledger-laelia", "version": 4},
        "created_at": "2026-08-08T10:00:00Z",
        "updated_at": "2026-08-08T10:01:00Z",
    }


def eligible():
    return {
        "contract": "calyx-eligible-reasoning-ledger-discovery-v1",
        "result": "ELIGIBLE_LEDGER_FOUND",
        "eligible_count": 1,
        "eligible_ledgers": [
            {
                "ledger_id": "ledger-laelia",
                "project_id": PROJECT_ID,
                "title": "Laelia anceps evidence review",
                "version": 5,
                "review_content_hash": "a" * 64,
                "current_content_hash": "b" * 64,
                "approved_review": {"reviewer": "owner-a"},
            }
        ],
        "read_only": True,
        "production_mutation": False,
        "publication_endpoint_invoked": False,
    }


def test_routes_are_mounted_through_calyx_core():
    paths = {route.path for route in calyx_core_router.routes}
    assert "/api/mission-control/calyx-owner-flow/start" in paths
    assert "/api/mission-control/calyx-owner-flow/{mission_id}" in paths
    assert "/api/mission-control/calyx-owner-flow/{mission_id}/review" in paths
    assert "/api/mission-control/calyx-owner-flow/{mission_id}/publication-candidate" in paths
    assert "/api/mission-control/calyx-owner-flow/{mission_id}/publish" in paths


def test_start_resolves_workspace_before_bounded_mission(monkeypatch):
    captured = {}

    def fake_start(**kwargs):
        captured.update(kwargs)
        return mission()

    monkeypatch.setattr(flow, "_resolve_project_id", lambda db, owner, requested: (PROJECT_ID, True))
    monkeypatch.setattr(flow.BRAIN_MISSION_SERVICE, "start", fake_start)
    monkeypatch.setattr(flow, "_persist_mission_ledger", lambda db, owner, item: None)
    response = client().post("/api/mission-control/calyx-owner-flow/start", json={})
    assert response.status_code == 201
    body = response.json()
    assert captured["question"] == flow.LAELIA_ANCEPS_QUESTION
    assert captured["tenant_id"] == "owner-a"
    assert captured["project_id"] == PROJECT_ID
    assert captured["max_steps"] <= 10
    assert body["workspace_project"] == {
        "project_id": PROJECT_ID,
        "created_for_flow": True,
        "owner_copied_project_id": False,
    }
    assert body["automatic_scientific_approval"] is False
    assert body["automatic_publication"] is False
    assert body["mission"]["private_reasoning_exposed"] is False


def test_status_exposes_plan_evidence_contradictions_gaps_and_ledger(monkeypatch):
    monkeypatch.setattr(flow, "_mission_for_owner", lambda mission_id, owner: mission())

    class FakeLedgerService:
        def __init__(self, db):
            pass

        def current(self, ledger_id, owner):
            return SimpleNamespace(ledger_id=ledger_id)

    monkeypatch.setattr(flow, "OperationalReasoningLedgerService", FakeLedgerService)
    monkeypatch.setattr(flow, "ledger_to_dict", lambda item: {"ledger_id": "ledger-laelia", "version": 4, "status": "under_review"})
    monkeypatch.setattr(flow, "discover_eligible_ledgers", lambda db, owner: {**eligible(), "eligible_count": 0, "eligible_ledgers": [], "result": "NO_ELIGIBLE_LEDGER"})
    monkeypatch.setattr(flow, "build_calyx_core_certification", lambda: {"overall_status": "ready", "operational_blockers": {}})

    response = client().get("/api/mission-control/calyx-owner-flow/mission-laelia")
    assert response.status_code == 200
    body = response.json()
    assert body["mission"]["plan"]["domains"] == ["taxonomy", "distribution", "pollination", "conservation", "mycorrhiza"]
    assert body["mission"]["evidence"]
    assert body["mission"]["contradicting_evidence"]
    assert body["mission"]["gaps"] == ["recent mycorrhizal field evidence"]
    assert body["reasoning_ledger"]["ledger_id"] == "ledger-laelia"
    assert body["owner_must_copy_hash_or_workflow_name"] is False


def test_review_uses_current_server_version_and_auth_reviewer(monkeypatch):
    monkeypatch.setattr(flow, "_mission_for_owner", lambda mission_id, owner: mission())
    captured = {}

    class FakeLedgerService:
        def __init__(self, db):
            pass

        def current(self, ledger_id, owner):
            return SimpleNamespace(version=4)

        def review(self, ledger_id, decision, *, owner, expected_version):
            captured.update(
                ledger_id=ledger_id,
                reviewer=decision.reviewer,
                outcome=decision.outcome.value,
                owner=owner,
                expected_version=expected_version,
            )
            return SimpleNamespace()

    monkeypatch.setattr(flow, "OperationalReasoningLedgerService", FakeLedgerService)
    monkeypatch.setattr(flow, "ledger_to_dict", lambda item: {"ledger_id": "ledger-laelia", "version": 5, "status": "approved"})
    monkeypatch.setattr(flow, "discover_eligible_ledgers", lambda db, owner: eligible())

    response = client().post(
        "/api/mission-control/calyx-owner-flow/mission-laelia/review",
        json={"outcome": "approved", "rationale": "I reviewed the evidence, contradictions, and provenance."},
    )
    assert response.status_code == 200
    assert captured == {
        "ledger_id": "ledger-laelia",
        "reviewer": "owner-a",
        "outcome": "approved",
        "owner": "owner-a",
        "expected_version": 4,
    }
    assert response.json()["publication_invoked"] is False
    assert response.json()["owner_copied_identifiers"] is False


def test_candidate_discovery_requires_no_hash_copying(monkeypatch):
    monkeypatch.setattr(flow, "_mission_for_owner", lambda mission_id, owner: mission())
    monkeypatch.setattr(flow, "discover_eligible_ledgers", lambda db, owner: eligible())
    response = client().get("/api/mission-control/calyx-owner-flow/mission-laelia/publication-candidate")
    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "MISSION_LEDGER_ELIGIBLE"
    assert body["candidate"]["ledger_id"] == "ledger-laelia"
    assert body["publication_invoked"] is False
    assert body["owner_copied_identifiers"] is False


def test_publication_impossible_without_explicit_confirmation(monkeypatch):
    called = {"discovery": 0, "publication": 0}
    monkeypatch.setattr(flow, "_mission_for_owner", lambda mission_id, owner: mission())

    def forbidden_discovery(db, owner):
        called["discovery"] += 1
        raise AssertionError("discovery must not run before confirmation")

    class ForbiddenPublication:
        def __init__(self, *args, **kwargs):
            called["publication"] += 1
            raise AssertionError("publication service must not run")

    monkeypatch.setattr(flow, "discover_eligible_ledgers", forbidden_discovery)
    monkeypatch.setattr(flow, "ReasoningLedgerPublicationService", ForbiddenPublication)
    response = client().post(
        "/api/mission-control/calyx-owner-flow/mission-laelia/publish",
        json={"explicit_owner_confirmation": False, "publication_note": "not confirmed"},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "EXPLICIT_OWNER_CONFIRMATION_REQUIRED"
    assert called == {"discovery": 0, "publication": 0}


def test_confirmed_publication_uses_server_discovered_version_and_hash_once(monkeypatch):
    monkeypatch.setattr(flow, "_mission_for_owner", lambda mission_id, owner: mission())
    monkeypatch.setattr(flow, "discover_eligible_ledgers", lambda db, owner: eligible())
    captured = {"calls": 0}

    class FakeGate:
        @classmethod
        def from_environment(cls):
            return object()

    class FakePublication:
        def __init__(self, db, gate):
            pass

        def publish(self, ledger_id, *, owner, expected_version, expected_review_content_hash, note):
            captured.update(
                calls=captured["calls"] + 1,
                ledger_id=ledger_id,
                owner=owner,
                version=expected_version,
                review_hash=expected_review_content_hash,
                note=note,
            )
            return (
                {
                    "publication_status": "published",
                    "canonical_publication_id": "publication-1",
                    "publication_gate_result": {
                        "graph": {"graph_version_id": 42},
                        "audit": {"result": "PASS"},
                    },
                },
                True,
            )

    monkeypatch.setattr(flow, "ExistingKnowledgeGraphPublicationGate", FakeGate)
    monkeypatch.setattr(flow, "ReasoningLedgerPublicationService", FakePublication)
    response = client().post(
        "/api/mission-control/calyx-owner-flow/mission-laelia/publish",
        json={"explicit_owner_confirmation": True, "publication_note": "owner-confirmed fixture"},
    )
    assert response.status_code == 200
    assert captured["calls"] == 1
    assert captured["ledger_id"] == "ledger-laelia"
    assert captured["version"] == 5
    assert captured["review_hash"] == "a" * 64
    body = response.json()
    assert body["result"] == "PUBLISHED"
    assert body["graph_version"] == 42
    assert body["audit_outcome"] == {"result": "PASS"}
    assert body["owner_copied_identifiers"] is False


def test_duplicate_replay_is_explicit_no_op(monkeypatch):
    monkeypatch.setattr(flow, "_mission_for_owner", lambda mission_id, owner: mission())
    monkeypatch.setattr(flow, "discover_eligible_ledgers", lambda db, owner: eligible())

    class FakeGate:
        @classmethod
        def from_environment(cls):
            return object()

    class ReplayPublication:
        def __init__(self, db, gate):
            pass

        def publish(self, *args, **kwargs):
            return (
                {
                    "publication_status": "published",
                    "canonical_publication_id": "publication-existing",
                    "publication_gate_result": {"graph": {"graph_version_id": 42}},
                },
                False,
            )

    monkeypatch.setattr(flow, "ExistingKnowledgeGraphPublicationGate", FakeGate)
    monkeypatch.setattr(flow, "ReasoningLedgerPublicationService", ReplayPublication)
    response = client().post(
        "/api/mission-control/calyx-owner-flow/mission-laelia/publish",
        json={"explicit_owner_confirmation": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "NO_OP_DUPLICATE_REPLAY"
    assert body["duplicate_replay_no_op"] is True
    assert "made no change" in body["plain_language_status"]
