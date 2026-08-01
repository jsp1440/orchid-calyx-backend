from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Index, String, Text, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.types import JSON

from app.database import Base

from .schemas import ArticleGenerationResponse, EvidencePreviewPacket


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JournalismEvidencePacketRecord(Base):
    __tablename__ = "calyx_journalism_evidence_packets"
    __table_args__ = (
        Index(
            "idx_calyx_journalism_packets_owner_created",
            "owner_subject",
            "created_at",
        ),
    )

    packet_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    actor_subject: Mapped[str] = mapped_column(Text, nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    request_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class JournalismArticleRecord(Base):
    __tablename__ = "calyx_journalism_articles"
    __table_args__ = (
        Index(
            "idx_calyx_journalism_articles_owner_created",
            "owner_subject",
            "created_at",
        ),
    )

    article_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    actor_subject: Mapped[str] = mapped_column(Text, nullable=False)
    generation_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_packet_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    request_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


TABLES = (
    JournalismEvidencePacketRecord.__table__,
    JournalismArticleRecord.__table__,
)


class SqlAlchemyJournalismRepository:
    """Owner-scoped durable storage for Calyx journalism artifacts."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def save_packet(
        self,
        packet: EvidencePreviewPacket,
        *,
        owner: str,
        actor: str,
        request_metadata: dict[str, Any] | None = None,
    ) -> EvidencePreviewPacket:
        packet_id = str(packet.packet_id)
        existing = self.db.get(JournalismEvidencePacketRecord, packet_id)
        if existing is not None:
            if existing.owner_subject != owner:
                raise LookupError("EVIDENCE_PACKET_NOT_FOUND")
            return EvidencePreviewPacket.model_validate(existing.payload)
        self.db.add(
            JournalismEvidencePacketRecord(
                packet_id=packet_id,
                owner_subject=owner,
                actor_subject=actor,
                generation_mode=str(packet.mode),
                payload=packet.model_dump(mode="json"),
                request_metadata=request_metadata or {},
                created_at=utcnow(),
            )
        )
        self.db.commit()
        return packet

    def get_packet(self, packet_id: str, *, owner: str) -> EvidencePreviewPacket | None:
        record = self.db.scalar(
            select(JournalismEvidencePacketRecord).where(
                JournalismEvidencePacketRecord.packet_id == packet_id,
                JournalismEvidencePacketRecord.owner_subject == owner,
            )
        )
        if record is None:
            return None
        return EvidencePreviewPacket.model_validate(record.payload)

    def save_article(
        self,
        article: ArticleGenerationResponse,
        *,
        owner: str,
        actor: str,
        evidence_packet_id: str | None,
        request_metadata: dict[str, Any] | None = None,
    ) -> ArticleGenerationResponse:
        article_id = str(article.article_id)
        existing = self.db.get(JournalismArticleRecord, article_id)
        if existing is not None:
            if existing.owner_subject != owner:
                raise LookupError("ARTICLE_NOT_FOUND")
            return ArticleGenerationResponse.model_validate(existing.payload)
        self.db.add(
            JournalismArticleRecord(
                article_id=article_id,
                owner_subject=owner,
                actor_subject=actor,
                generation_mode=str(article.mode),
                evidence_packet_id=evidence_packet_id,
                payload=article.model_dump(mode="json"),
                request_metadata=request_metadata or {},
                created_at=utcnow(),
            )
        )
        self.db.commit()
        return article

    def get_article(self, article_id: str, *, owner: str) -> ArticleGenerationResponse | None:
        record = self.db.scalar(
            select(JournalismArticleRecord).where(
                JournalismArticleRecord.article_id == article_id,
                JournalismArticleRecord.owner_subject == owner,
            )
        )
        if record is None:
            return None
        return ArticleGenerationResponse.model_validate(record.payload)
