from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.conversation_memory.models import ConversationMessage, ConversationSession
from app.conversation_memory.report import build_conversation_markdown
from app.database import Base, get_db
from app.research_workspace.models import Project
from app.routers import calyx_operator_chat as api
from app.security import verify_owner_or_api_key


def report_fixture():
    now = datetime(2026, 8, 8, 19, 0, tzinfo=timezone.utc)
    return {
        "conversation_id": "conversation-fixture",
        "title": "Pollination evidence",
        "project_id": "project-fixture",
        "active_taxon_id": "taxon:fixture",
        "active_document_id": "document-fixture",
        "created_at": now,
        "updated_at": now,
        "messages": [
            {
                "message_id": "operator-1",
                "role": "OPERATOR",
                "content": "What does this paper report?",
                "created_at": now,
                "data_status": "CONVERSATION_CONTEXT",
                "context": {
                    "active_project_id": "project-fixture",
                    "active_taxon_id": "taxon:fixture",
                    "active_document_id": "document-fixture",
                },
                "source_refs": [],
            },
            {
                "message_id": "calyx-1",
                "role": "CALYX",
                "content": "The governed Continuum evidence reports a pollination observation.",
                "created_at": now,
                "data_status": "CONVERSATION_CONTEXT",
                "epistemic_status": "continuum_evidence",
                "context": {
                    "active_project_id": "project-fixture",
                    "active_taxon_id": "taxon:fixture",
                    "active_document_id": "document-fixture",
                },
                "source_refs": [
                    {
                        "result_id": "result-1",
                        "object_type": "CLAIM",
                        "title": "Pollination study",
                        "citation": {
                            "document_title": "Pollination study",
                            "revision_id": "rev-1",
                            "identifier": "doi:fixture",
                            "locator": "p. 4",
                        },
                    }
                ],
            },
        ],
    }


def test_report_preserves_context_sources_and_non_authority_language():
    report = build_conversation_markdown(report_fixture())

    assert "# Calyx Research Conversation Report" in report
    assert "document-fixture" in report
    assert "continuum_evidence" in report
    assert "Pollination study" in report
    assert "doi:fixture" in report
    assert "not scientific evidence" in report
    assert "Scientific publication authorized: `false`" in report
    assert "Knowledge Graph mutation authorized: `false`" in report
    assert "not a peer-reviewed scientific conclusion" in report


def test_report_deduplicates_persisted_source_references():
    fixture = report_fixture()
    fixture["messages"].append(dict(fixture["messages"][1], message_id="calyx-2"))
    report = build_conversation_markdown(fixture)

    assert report.count('<a id="source-1"></a>Source 1:') == 1
    assert "### Source 2:" not in report
    assert (
        report.count("- Sources: [Source 1](#source-1)") == 2
    )  # one per Calyx message


def test_owner_scoped_report_endpoint_returns_markdown_attachment():
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
            ConversationSession.__table__,
            ConversationMessage.__table__,
        ],
    )
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    with SessionLocal() as db:
        session = ConversationSession(
            owner_subject="owner-report", title="Export fixture"
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        conversation_id = session.conversation_id
        db.add_all(
            [
                ConversationMessage(
                    conversation_id=conversation_id,
                    owner_subject="owner-report",
                    role="OPERATOR",
                    content="Question fixture",
                ),
                ConversationMessage(
                    conversation_id=conversation_id,
                    owner_subject="owner-report",
                    role="CALYX",
                    content="Answer fixture",
                    epistemic_status="unknown",
                ),
            ]
        )
        db.commit()

    app = FastAPI()
    app.include_router(api.router)

    def override_get_db():
        with SessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "owner-report",
        "auth_type": "test",
    }
    client = TestClient(app)

    response = client.get(
        f"/brain/mission-control/chat/conversations/{conversation_id}/report"
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert (
        f"calyx-conversation-{conversation_id}.md"
        in response.headers["content-disposition"]
    )
    assert "Question fixture" in response.text
    assert "Answer fixture" in response.text

    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "different-owner",
        "auth_type": "test",
    }
    isolated = client.get(
        f"/brain/mission-control/chat/conversations/{conversation_id}/report"
    )
    assert isolated.status_code == 404
