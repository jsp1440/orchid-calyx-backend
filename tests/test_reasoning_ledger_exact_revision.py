from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.reasoning_ledger.models import (
    LedgerEntry,
    LedgerEntryKind,
    UncertaintyMarker,
)
from app.reasoning_ledger.operational_service import OperationalReasoningLedgerService
from app.reasoning_ledger.persistence import (
    TABLES,
    ReasoningLedgerRevision,
    SqlAlchemyReasoningLedgerRepository,
)
from app.reasoning_ledger.routes import router
from app.research_workspace.models import Project
from app.security import verify_owner_or_api_key

OWNER = "owner-a"
OTHER = "owner-b"


def _database():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={
            "schema_translate_map": {
                "research_station": None,
                "reasoning_ledger": None,
            }
        },
    )
    Base.metadata.create_all(engine, tables=[Project.__table__, *TABLES])
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _project(db: Session, owner: str = OWNER) -> str:
    project = Project(owner_subject=owner, title="Reasoning project", description="")
    db.add(project)
    db.commit()
    return str(project.project_id)


def _ledger(db: Session) -> str:
    project_id = _project(db)
    service = OperationalReasoningLedgerService(db)
    ledger, _ = service.create(
        owner=OWNER, project_id=project_id, title="Question", description=""
    )
    ledger_id = str(ledger.ledger_id)
    for index, text in enumerate(("first", "second"), start=1):
        service.append(
            ledger_id,
            LedgerEntry(
                kind=LedgerEntryKind.SUPPORT,
                text=text,
                author=OWNER,
                tenant_id=OWNER,
                project_id=project_id,
                uncertainty=UncertaintyMarker(confidence=0.7),
            ),
            owner=OWNER,
            expected_version=index,
        )
    return ledger_id


@pytest.fixture
def api():
    session_local = _database()
    with session_local() as db:
        ledger_id = _ledger(db)
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[verify_owner_or_api_key] = lambda: {
            "actor": OWNER,
            "auth_type": "owner_session",
        }
        with TestClient(app) as client:
            yield app, client, db, ledger_id


def test_returns_the_exact_requested_revision(api):
    _, client, _, ledger_id = api

    response = client.get(f"/api/reasoning-ledgers/{ledger_id}/revisions/2")

    assert response.status_code == 200
    body = response.json()
    assert body["requested_version"] == 2
    assert body["revision"]["version"] == 2
    assert [entry["text"] for entry in body["revision"]["entries"]] == ["first"]


def test_missing_exact_revision_never_falls_back_to_latest(api):
    _, client, _, ledger_id = api

    response = client.get(f"/api/reasoning-ledgers/{ledger_id}/revisions/9")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "LEDGER_REVISION_NOT_FOUND"
    assert response.json()["detail"]["requested_version"] == 9


def test_missing_exact_revision_reports_available_versions(api):
    _, client, db, ledger_id = api
    db.query(ReasoningLedgerRevision).filter_by(ledger_id=ledger_id, version=2).delete()
    db.commit()

    detail = client.get(f"/api/reasoning-ledgers/{ledger_id}/revisions/2").json()[
        "detail"
    ]

    assert detail["code"] == "LEDGER_REVISION_NOT_FOUND"
    assert detail["available_versions"] == [1, 3]


@pytest.mark.parametrize("version", ["0", "-1", "abc", "1.5"])
def test_invalid_version_is_rejected_with_contract_code(api, version):
    _, client, _, ledger_id = api

    response = client.get(f"/api/reasoning-ledgers/{ledger_id}/revisions/{version}")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "LEDGER_REVISION_INVALID"


def test_unknown_ledger_is_distinguished_from_missing_revision(api):
    _, client, _, ledger_id = api

    unknown = client.get("/api/reasoning-ledgers/unknown/revisions/1")
    missing = client.get(f"/api/reasoning-ledgers/{ledger_id}/revisions/9")

    assert unknown.status_code == missing.status_code == 404
    assert unknown.json()["detail"] == {"code": "LEDGER_NOT_FOUND"}
    assert missing.json()["detail"]["code"] == "LEDGER_REVISION_NOT_FOUND"


def test_owner_isolation_does_not_reveal_versions(api):
    app, _, _, ledger_id = api
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": OTHER,
        "auth_type": "owner_session",
    }
    with TestClient(app) as client:
        response = client.get(f"/api/reasoning-ledgers/{ledger_id}/revisions/1")

    assert response.status_code == 404
    assert response.json()["detail"] == {"code": "LEDGER_NOT_FOUND"}


def test_canonical_serializer_is_used_and_retrieval_is_not_certification(
    api, monkeypatch
):
    _, client, _, ledger_id = api
    seen = []

    def canonical_projection(ledger):
        seen.append(ledger.version)
        return {"version": ledger.version, "canonical": True}

    monkeypatch.setattr(
        "app.reasoning_ledger.routes.ledger_to_dict", canonical_projection
    )
    body = client.get(f"/api/reasoning-ledgers/{ledger_id}/revisions/2").json()

    assert seen == [2]
    assert body["revision"] == {"version": 2, "canonical": True}
    assert body["inspectable"] is True
    assert body["reasoning_certified"] is False


def test_exact_retrieval_does_not_call_history_or_audit_history(api, monkeypatch):
    _, client, _, ledger_id = api

    def forbidden(*_args, **_kwargs):
        raise AssertionError("exact revision retrieval must not load full history")

    monkeypatch.setattr(SqlAlchemyReasoningLedgerRepository, "history", forbidden)
    monkeypatch.setattr(SqlAlchemyReasoningLedgerRepository, "audit_history", forbidden)

    response = client.get(f"/api/reasoning-ledgers/{ledger_id}/revisions/2")

    assert response.status_code == 200


def test_persistence_failure_is_503_not_an_empty_ledger(api, monkeypatch):
    _, client, _, ledger_id = api

    def unavailable(*_args, **_kwargs):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(OperationalReasoningLedgerService, "revision", unavailable)
    response = client.get(f"/api/reasoning-ledgers/{ledger_id}/revisions/2")

    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "LEDGER_PERSISTENCE_UNAVAILABLE"}
