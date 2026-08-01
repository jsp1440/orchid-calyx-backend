from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.calyx_agent.service import CalyxAgentService
from app.calyx_journalism.persistence import (
    TABLES,
    SqlAlchemyJournalismRepository,
)
from app.calyx_journalism.schemas import (
    ArticleBrief,
    ArticleGenerationRequest,
    GenerationMode,
    PublicationMeta,
)
from app.calyx_journalism.services import ArticleGenerationService, EvidencePreviewService


def _engine():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in TABLES:
        table.create(engine)
    return engine


def _request(packet_id: str | None = None) -> ArticleGenerationRequest:
    return ArticleGenerationRequest(
        publication=PublicationMeta(
            publication_id="continuum-report",
            publication_name="Orchid Continuum",
            theme="conservation",
        ),
        brief=ArticleBrief(
            title="Orchid conservation status",
            focus="Use verified evidence only.",
            target_word_count_min=100,
            target_word_count_max=500,
        ),
        generation_mode=GenerationMode(
            mode="limited_evidence",
            unavailable_dependencies=["external_model"],
        ),
        evidence_packet_id=packet_id,
    )


def test_packet_survives_fresh_session() -> None:
    engine = _engine()
    packet = EvidencePreviewService().build_preview(
        evidence_items=[{"project_name": "Andes Orchid Fund", "country": "Ecuador"}],
        available_dependencies=[],
    )
    with Session(engine) as first:
        SqlAlchemyJournalismRepository(first).save_packet(
            packet, owner="owner-1", actor="owner-1"
        )
    with Session(engine) as second:
        restored = SqlAlchemyJournalismRepository(second).get_packet(
            str(packet.packet_id), owner="owner-1"
        )
    assert restored is not None
    assert restored.model_dump(mode="json") == packet.model_dump(mode="json")


def test_packet_is_owner_scoped() -> None:
    engine = _engine()
    packet = EvidencePreviewService().build_preview(evidence_items=[], available_dependencies=[])
    with Session(engine) as db:
        repository = SqlAlchemyJournalismRepository(db)
        repository.save_packet(packet, owner="owner-1", actor="owner-1")
        assert repository.get_packet(str(packet.packet_id), owner="owner-2") is None


def test_article_survives_fresh_session() -> None:
    engine = _engine()
    request = _request()
    article = ArticleGenerationService().generate(request)
    with Session(engine) as first:
        SqlAlchemyJournalismRepository(first).save_article(
            article,
            owner="owner-1",
            actor="owner-1",
            evidence_packet_id=None,
        )
    with Session(engine) as second:
        restored = SqlAlchemyJournalismRepository(second).get_article(
            str(article.article_id), owner="owner-1"
        )
    assert restored is not None
    assert restored.model_dump(mode="json") == article.model_dump(mode="json")


def test_agent_recognizes_journalism_request_without_publishing() -> None:
    response = CalyxAgentService().handle(
        actor="owner-1",
        request_text="Prepare an article about global orchid conservation.",
    )
    tool_ids = [result.tool_id for result in response.tool_results]
    assert "journalism.readiness" in tool_ids
    assert response.approval_required is False
    assert any(step.action_class.value == "prepare_only" for step in response.steps)
    assert all("publish" not in step.status for step in response.steps)


def test_agent_blocks_direct_publication_request() -> None:
    response = CalyxAgentService().handle(
        actor="owner-1",
        request_text="Publish scientific canonical knowledge from this article.",
    )
    assert response.approval_required is True
    assert response.steps[0].status == "blocked_pending_approval"
