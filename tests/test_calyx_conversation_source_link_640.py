from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.conversation_memory.models import ConversationMessage, ConversationSession
from app.database import Base, get_db
from app.research_workspace.models import Project, ProjectDocument
from app.research_workspace.service import ResearchWorkspaceService
from app.routers import calyx_conversation_sources as api
from app.security import verify_owner_or_api_key


class AllowDocumentValidator:
    def require(self, kind, identifier):
        assert kind == "document"
        assert identifier == "document-source"


def make_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        execution_options={"schema_translate_map": {"research_station": None}},
    )
    Base.metadata.create_all(
        engine,
        tables=[
            Project.__table__,
            ProjectDocument.__table__,
            ConversationSession.__table__,
            ConversationMessage.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as db:
        project = Project(owner_subject="owner-640", title="Source project", description="")
        db.add(project)
        db.flush()
        conversation = ConversationSession(
            owner_subject="owner-640",
            project_id=project.project_id,
            title="Source thread",
        )
        db.add(conversation)
        db.flush()
        db.add(
            ConversationMessage(
                conversation_id=conversation.conversation_id,
                owner_subject="owner-640",
                role="CALYX",
                content="Grounded answer",
                source_refs_json=[
                    {
                        "result_id": "result-source",
                        "object_type": "CLAIM",
                        "title": "Source paper",
                        "citation": {
                            "document_id": "document-source",
                            "revision_id": "revision-source",
                            "identifier": "doi:source",
                        },
                    }
                ],
            )
        )
        db.commit()
        conversation_id = conversation.conversation_id
        project_id = project.project_id

    app = FastAPI()
    app.include_router(api.router)

    def override_get_db():
        with SessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "owner-640",
        "auth_type": "test",
    }
    original = api.ResearchWorkspaceService
    api.ResearchWorkspaceService = lambda db: ResearchWorkspaceService(
        db, validator=AllowDocumentValidator()
    )
    return TestClient(app), app, SessionLocal, conversation_id, project_id, original


def test_persisted_source_can_be_linked_to_its_conversation_project_idempotently():
    client, _app, SessionLocal, conversation_id, project_id, original = make_client()
    try:
        first = client.post(
            f"/brain/mission-control/chat/conversations/{conversation_id}/sources/result-source/project-link",
            json={"relationship": "SOURCE"},
        )
        second = client.post(
            f"/brain/mission-control/chat/conversations/{conversation_id}/sources/result-source/project-link",
            json={"relationship": "SOURCE"},
        )

        assert first.status_code == 201
        assert second.status_code == 201
        payload = first.json()
        assert payload["project_id"] == project_id
        assert payload["document_id"] == "document-source"
        assert payload["revision_id"] == "revision-source"
        assert payload["conversation_history_is_evidence"] is False
        assert payload["scientific_publication_authorized"] is False
        assert payload["knowledge_graph_mutation_authorized"] is False
        with SessionLocal() as db:
            assert db.query(ProjectDocument).count() == 1
    finally:
        api.ResearchWorkspaceService = original


def test_source_link_rejects_unknown_source_and_missing_document_identity():
    client, _app, SessionLocal, conversation_id, _project_id, original = make_client()
    try:
        missing = client.post(
            f"/brain/mission-control/chat/conversations/{conversation_id}/sources/not-present/project-link",
            json={},
        )
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "CONVERSATION_SOURCE_NOT_FOUND"

        with SessionLocal() as db:
            message = db.query(ConversationMessage).one()
            message.source_refs_json = [{"result_id": "without-document", "citation": {}}]
            db.commit()
        unavailable = client.post(
            f"/brain/mission-control/chat/conversations/{conversation_id}/sources/without-document/project-link",
            json={},
        )
        assert unavailable.status_code == 422
        assert (
            unavailable.json()["detail"]["code"]
            == "CONVERSATION_SOURCE_DOCUMENT_ID_UNAVAILABLE"
        )
    finally:
        api.ResearchWorkspaceService = original


def test_source_link_is_owner_scoped():
    client, app, _SessionLocal, conversation_id, _project_id, original = make_client()
    try:
        app.dependency_overrides[verify_owner_or_api_key] = lambda: {
            "actor": "different-owner",
            "auth_type": "test",
        }
        response = client.post(
            f"/brain/mission-control/chat/conversations/{conversation_id}/sources/result-source/project-link",
            json={},
        )
        assert response.status_code == 404
    finally:
        api.ResearchWorkspaceService = original
