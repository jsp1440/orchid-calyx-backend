from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.conversation_memory.models import ConversationMessage, ConversationSession
from app.database import Base, get_db
from app.research_workspace.models import Project
from app.routers import calyx_operator_chat as api
from app.security import verify_owner_or_api_key
from runtime.continuum_conversation import ContinuumConversationService


class FakeRetrieval:
    def search(self, query):
        return {
            "retrieval_mode": query.mode,
            "ranking_configuration_version": "test-rank-v1",
            "total_candidates": 1,
            "total_eligible_results": 1,
            "elapsed_ms": 0.5,
            "results": [
                {
                    "result_id": "result-636",
                    "rank": 1,
                    "fused_score": 0.92,
                    "object_type": "CLAIM",
                    "title": "Persistent source",
                    "authorized_excerpt": "Authorized excerpt should not be duplicated into source refs.",
                    "citation": {
                        "document_title": "Persistent source",
                        "revision_id": "rev-636",
                        "locator": "p. 6",
                        "identifier": "doi:fixture",
                    },
                    "reliability_signals": {"evidence_type": "PRIMARY"},
                    "review_state": "REVIEWED",
                    "verification_state": "VERIFIED",
                    "temporal_status": "CURRENT",
                    "display_policy": "LIMITED_PREVIEW_ONLY",
                    "collections": ["literature"],
                }
            ],
        }


def test_persistent_conversation_round_trip_and_owner_isolation(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api.reset_chat_for_tests()
    monkeypatch.setattr(api, "_continuum", ContinuumConversationService(FakeRetrieval()))

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"research_station": None}},
    )
    Base.metadata.create_all(
        engine,
        tables=[Project.__table__, ConversationSession.__table__, ConversationMessage.__table__],
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as db:
        project = Project(owner_subject="owner-636", title="Persistent project", description="")
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.project_id

    app = FastAPI()
    app.include_router(api.router)

    def override_get_db():
        with SessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "owner-636",
        "auth_type": "test",
    }
    client = TestClient(app)

    created = client.post(
        "/brain/mission-control/chat/conversations",
        json={
            "project_id": project_id,
            "title": "Pollination thread",
            "active_taxon_id": "taxon:fixture",
        },
    )
    assert created.status_code == 201
    conversation = created.json()
    conversation_id = conversation["conversation_id"]
    assert conversation["data_status"] == "CONVERSATION_CONTEXT"
    assert conversation["evidence_authority"] is False

    response = client.post(
        f"/brain/mission-control/chat/conversations/{conversation_id}/ask",
        json={"question": "What does the current evidence say?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["persistent"] is True
    assert payload["conversation_history_is_evidence"] is False
    assert payload["context"]["active_project_id"] == project_id
    assert payload["context"]["active_taxon_id"] == "taxon:fixture"
    assert len(payload["persisted_messages"]) == 2
    assert all(item["data_status"] == "CONVERSATION_CONTEXT" for item in payload["persisted_messages"])
    assert all(item["evidence_authority"] is False for item in payload["persisted_messages"])

    fetched = client.get(
        f"/brain/mission-control/chat/conversations/{conversation_id}"
    )
    assert fetched.status_code == 200
    messages = fetched.json()["messages"]
    assert [message["role"] for message in messages] == ["OPERATOR", "CALYX"]
    assert messages[1]["source_refs"][0]["result_id"] == "result-636"
    assert "Authorized excerpt should not be duplicated" not in str(messages[1]["source_refs"])

    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "different-owner",
        "auth_type": "test",
    }
    isolated = client.get(
        f"/brain/mission-control/chat/conversations/{conversation_id}"
    )
    assert isolated.status_code == 404


def test_persistent_ask_can_explicitly_clear_stored_taxon_context(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api.reset_chat_for_tests()
    monkeypatch.setattr(api, "_continuum", ContinuumConversationService(FakeRetrieval()))

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"research_station": None}},
    )
    Base.metadata.create_all(
        engine,
        tables=[Project.__table__, ConversationSession.__table__, ConversationMessage.__table__],
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    app = FastAPI()
    app.include_router(api.router)

    def override_get_db():
        with SessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "owner-clear",
        "auth_type": "test",
    }
    client = TestClient(app)
    created = client.post(
        "/brain/mission-control/chat/conversations",
        json={"active_taxon_id": "taxon:stored"},
    ).json()

    response = client.post(
        f"/brain/mission-control/chat/conversations/{created['conversation_id']}/ask",
        json={
            "question": "Use evidence only for this turn.",
            "context": {"active_taxon_id": None},
        },
    )
    assert response.status_code == 200
    assert response.json()["context"]["active_taxon_id"] is None
    fetched = client.get(
        f"/brain/mission-control/chat/conversations/{created['conversation_id']}"
    ).json()
    assert fetched["active_taxon_id"] is None


def test_migration_makes_messages_append_only_and_non_authoritative():
    migration = Path("migrations/140_calyx_conversation_sessions.sql").read_text()
    assert "BEFORE UPDATE OR DELETE ON research_station.conversation_messages" in migration
    assert "evidence_authority BOOLEAN NOT NULL DEFAULT FALSE" in migration
    assert "CHECK (evidence_authority = FALSE)" in migration
    assert "scientific_publication_authorized BOOLEAN NOT NULL DEFAULT FALSE" in migration
    assert "knowledge_graph_mutation_authorized BOOLEAN NOT NULL DEFAULT FALSE" in migration
