from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.reasoning_ledger.service import LedgerNotFoundError, LedgerValidationError
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


def test_start_mission_derives_tenant_actor_and_persists_ledger(monkeypatch):
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
            "publication_eligibility": {
                "eligible": False,
                "automatic_publication": False,
                "blockers": ["HUMAN_REVIEW_REQUIRED"],
            },
            "reasoning_ledger": {"ledger_id": "ledger-1", "version": 1},
            "created_at": "now",
            "updated_at": "now",
        }

    def fake_persist(db, owner, mission):
        captured["persist_owner"] = owner
        captured["persist_ledger_id"] = mission["reasoning_ledger"]["ledger_id"]
        return SimpleNamespace(version=mission["reasoning_ledger"]["version"])

    monkeypatch.setattr(operator.BRAIN_MISSION_SERVICE, "start", fake_start)
    monkeypatch.setattr(operator, "_persist_mission_ledger", fake_persist)
    response = _client().post(
        "/api/mission-control/calyx-operator/missions",
        json={
            "question": "What evidence supports this orchid relationship?",
            "project_id": "project-1",
        },
    )
    assert response.status_code == 201
    assert captured["tenant_id"] == "owner-a"
    assert captured["actor"] == "owner-a"
    assert captured["persist_owner"] == "owner-a"
    assert captured["persist_ledger_id"] == "ledger-1"
    assert response.json()["automatic_publication"] is False


def test_mission_ledger_handoff_is_idempotent_and_fingerprint_exact(monkeypatch):
    source_entries = (
        SimpleNamespace(fingerprint="fingerprint-1"),
        SimpleNamespace(fingerprint="fingerprint-2"),
    )
    source = SimpleNamespace(
        ledger_id="00000000-0000-0000-0000-000000000001",
        tenant_id="owner-a",
        project_id="project-1",
        title="Brain mission m1",
        description="question",
        entries=source_entries,
        version=3,
    )
    monkeypatch.setattr(
        operator.BRAIN_MISSION_ADAPTER.ledgers,
        "current",
        lambda ledger_id, *, tenant_id: source,
    )

    state = {"ledger": None, "append_calls": 0}

    class FakeOperationalService:
        def __init__(self, db):
            pass

        def current(self, ledger_id, owner):
            if state["ledger"] is None:
                raise LedgerNotFoundError("missing")
            return state["ledger"]

        def create(self, *, owner, project_id, title, description):
            state["ledger"] = SimpleNamespace(
                ledger_id=source.ledger_id,
                tenant_id=owner,
                project_id=project_id,
                title=title,
                description=description,
                entries=(),
                version=1,
            )
            return state["ledger"], True

        def append(self, ledger_id, entry, *, owner, expected_version):
            current = state["ledger"]
            assert expected_version == current.version
            state["append_calls"] += 1
            state["ledger"] = SimpleNamespace(
                ledger_id=current.ledger_id,
                tenant_id=current.tenant_id,
                project_id=current.project_id,
                title=current.title,
                description=current.description,
                entries=(*current.entries, entry),
                version=current.version + 1,
            )
            return state["ledger"]

    monkeypatch.setattr(operator, "OperationalReasoningLedgerService", FakeOperationalService)
    mission = {"reasoning_ledger": {"ledger_id": source.ledger_id, "version": 3}}

    first = operator._persist_mission_ledger(FakeDb(), "owner-a", mission)
    second = operator._persist_mission_ledger(FakeDb(), "owner-a", mission)

    assert first.version == source.version
    assert second.version == source.version
    assert [entry.fingerprint for entry in second.entries] == [
        "fingerprint-1",
        "fingerprint-2",
    ]
    assert state["append_calls"] == 2


def test_mission_ledger_handoff_fails_closed_on_durable_divergence(monkeypatch):
    source = SimpleNamespace(
        ledger_id="00000000-0000-0000-0000-000000000001",
        tenant_id="owner-a",
        project_id="project-1",
        title="Brain mission m1",
        description="question",
        entries=(SimpleNamespace(fingerprint="expected"),),
        version=2,
    )
    durable = SimpleNamespace(
        ledger_id=source.ledger_id,
        tenant_id=source.tenant_id,
        project_id=source.project_id,
        title=source.title,
        description=source.description,
        entries=(SimpleNamespace(fingerprint="different"),),
        version=2,
    )
    monkeypatch.setattr(
        operator.BRAIN_MISSION_ADAPTER.ledgers,
        "current",
        lambda ledger_id, *, tenant_id: source,
    )

    class DivergedOperationalService:
        def __init__(self, db):
            pass

        def current(self, ledger_id, owner):
            return durable

    monkeypatch.setattr(
        operator,
        "OperationalReasoningLedgerService",
        DivergedOperationalService,
    )
    mission = {"reasoning_ledger": {"ledger_id": source.ledger_id, "version": 2}}

    with pytest.raises(LedgerValidationError, match="MISSION_LEDGER_DIVERGED"):
        operator._persist_mission_ledger(FakeDb(), "owner-a", mission)


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
    monkeypatch.setattr(
        operator,
        "ledger_to_dict",
        lambda ledger: {"ledger_id": "ledger-1", "version": 2},
    )
    response = _client().post(
        "/api/mission-control/calyx-operator/ledgers/ledger-1/review",
        json={
            "expected_version": 1,
            "outcome": "approved",
            "rationale": "Evidence and provenance reviewed.",
        },
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

    monkeypatch.setattr(
        operator,
        "ReasoningLedgerPublicationService",
        ForbiddenPublicationService,
    )
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
        lambda: {
            "overall_status": "partial_operational_readiness",
            "operational_blockers": {"occurrences": ["durable persistence missing"]},
        },
    )
    response = _client().get("/api/mission-control/calyx-operator/graph/version")
    assert response.status_code == 200
    payload = response.json()
    assert payload["graph_version"] is None
    assert payload["version_state"] == "NOT_ASSERTED_BY_OPERATOR_FACADE"
    assert payload["production_graph_mutation"] is False
