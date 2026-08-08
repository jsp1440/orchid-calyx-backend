from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConversationSession(Base):
    __tablename__ = "conversation_sessions"
    __table_args__ = (
        Index(
            "idx_rs_conversation_owner_project_updated",
            "owner_subject",
            "project_id",
            "updated_at",
        ),
        {"schema": "research_station"},
    )

    conversation_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("research_station.projects.project_id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="Calyx conversation")
    active_taxon_id: Mapped[str | None] = mapped_column(Text)
    active_document_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"
    __table_args__ = (
        CheckConstraint("role IN ('OPERATOR','CALYX')", name="ck_rs_conversation_message_role"),
        CheckConstraint(
            "data_status = 'CONVERSATION_CONTEXT'",
            name="ck_rs_conversation_message_status",
        ),
        Index(
            "idx_rs_conversation_messages_session_time",
            "conversation_id",
            "created_at",
            "message_id",
        ),
        {"schema": "research_station"},
    )

    message_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.conversation_sessions.conversation_id"),
        nullable=False,
    )
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    epistemic_status: Mapped[str | None] = mapped_column(String(64))
    context_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    source_refs_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    tool_trace_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=list
    )
    data_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="CONVERSATION_CONTEXT"
    )
    evidence_authority: Mapped[bool] = mapped_column(nullable=False, default=False)
    scientific_publication_authorized: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )
    knowledge_graph_mutation_authorized: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
