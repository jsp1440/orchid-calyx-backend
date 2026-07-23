from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Uuid,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProjectStatus(StrEnum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','PAUSED','COMPLETED')"),
        Index(
            "idx_rs_projects_owner_archive_updated",
            "owner_subject",
            "archived_at",
            "updated_at",
        ),
        {"schema": "research_station"},
    )
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    research_question: Mapped[str | None] = mapped_column(Text)
    hypothesis: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ProjectStatus.ACTIVE.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class SavedSearch(Base):
    __tablename__ = "saved_searches"
    __table_args__ = ({"schema": "research_station"},)
    saved_search_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id"),
        nullable=False,
    )
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    query_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    result_count_snapshot: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class Note(Base):
    __tablename__ = "notes"
    __table_args__ = ({"schema": "research_station"},)
    note_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id"),
        nullable=False,
    )
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    note_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="GENERAL"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class ProjectTaxon(Base):
    __tablename__ = "project_taxa"
    __table_args__ = ({"schema": "research_station"},)
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id"),
        primary_key=True,
    )
    taxon_id: Mapped[str] = mapped_column(Text, primary_key=True)
    relationship: Mapped[str] = mapped_column(String(20), default="SUBJECT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    created_by_subject: Mapped[str] = mapped_column(Text, nullable=False)


class ProjectDocument(Base):
    __tablename__ = "project_documents"
    __table_args__ = ({"schema": "research_station"},)
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id"),
        primary_key=True,
    )
    document_id: Mapped[str] = mapped_column(Text, primary_key=True)
    revision_id: Mapped[str | None] = mapped_column(Text)
    relationship: Mapped[str] = mapped_column(String(20), default="SOURCE")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    created_by_subject: Mapped[str] = mapped_column(Text, nullable=False)


class ProjectEvidence(Base):
    __tablename__ = "project_evidence"
    __table_args__ = ({"schema": "research_station"},)
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id"),
        primary_key=True,
    )
    evidence_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(Text, primary_key=True)
    relationship: Mapped[str] = mapped_column(String(20), default="SUPPORTS")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    created_by_subject: Mapped[str] = mapped_column(Text, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = ({"schema": "research_station"},)
    event_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id"),
        nullable=False,
    )
    actor_subject: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    request_correlation_id: Mapped[str | None] = mapped_column(Text)
    change_summary: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
