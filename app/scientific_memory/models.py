from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScientificMemoryCapture(Base):
    __tablename__ = "scientific_memory_captures"
    __table_args__ = (
        CheckConstraint("origin IN ('OASIS','CALYX','RESEARCH_STATION')"),
        UniqueConstraint(
            "project_id", "fingerprint", name="uq_rs_memory_capture_fingerprint"
        ),
        Index("idx_rs_memory_capture_project_time", "project_id", "created_at"),
        {"schema": "research_station"},
    )

    capture_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id"),
        nullable=False,
    )
    saved_search_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.saved_searches.saved_search_id"),
        nullable=False,
    )
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(24), nullable=False)
    conversation_id: Mapped[str | None] = mapped_column(Text)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ScientificMemoryItem(Base):
    __tablename__ = "scientific_memory_items"
    __table_args__ = (
        CheckConstraint(
            "item_type IN ('EVIDENCE','CLAIM','RELATIONSHIP','TRAIT','METHOD',"
            "'MATERIAL','PROTOCOL','MEASUREMENT','TAXON_MAPPING','CONTRADICTION',"
            "'UNCERTAINTY','ANALYSIS')"
        ),
        CheckConstraint(
            "authority IN ('SOURCE_EVIDENCE','CANDIDATE_KNOWLEDGE',"
            "'CALYX_INFERENCE','RESEARCH_CONTEXT')"
        ),
        CheckConstraint(
            "rights_basis IN ('OPEN_ACCESS','AUTHORIZED','USER_PROVIDED','METADATA_ONLY')"
        ),
        Index("idx_rs_memory_item_project_type", "project_id", "item_type"),
        {"schema": "research_station"},
    )

    memory_item_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    capture_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.scientific_memory_captures.capture_id"),
        nullable=False,
    )
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id"),
        nullable=False,
    )
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    authority: Mapped[str] = mapped_column(String(32), nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    document_id: Mapped[str | None] = mapped_column(Text)
    revision_id: Mapped[str | None] = mapped_column(Text)
    source_identifier: Mapped[str | None] = mapped_column(Text)
    source_locator: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    authorized_excerpt: Mapped[str | None] = mapped_column(Text)
    rights_basis: Mapped[str] = mapped_column(String(24), nullable=False)
    structured_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    correction_of_item_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.scientific_memory_items.memory_item_id"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class ScientificMemoryDecision(Base):
    __tablename__ = "scientific_memory_decisions"
    __table_args__ = (
        CheckConstraint("action IN ('ACCEPT_REVIEW','REJECT','INVALIDATE','CORRECT')"),
        Index("idx_rs_memory_decision_item_time", "memory_item_id", "created_at"),
        {"schema": "research_station"},
    )

    decision_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id"),
        nullable=False,
    )
    memory_item_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.scientific_memory_items.memory_item_id"),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_subject: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    replacement_item_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.scientific_memory_items.memory_item_id"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
