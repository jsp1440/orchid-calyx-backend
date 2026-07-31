from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.types import JSON

from app.database import Base

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class ReasoningPublicationArtifactRow(Base):
    __tablename__ = "publication_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ledger_id"],
            ["reasoning_ledger.ledger_heads.ledger_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("artifact_hash"),
        UniqueConstraint(
            "ledger_id", "ledger_version", "review_content_hash", "artifact_hash"
        ),
        Index(
            "idx_reasoning_publication_scope",
            "owner_subject",
            "project_id",
            "created_at",
        ),
        {"schema": "reasoning_publication"},
    )
    publication_artifact_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ledger_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ledger_version: Mapped[int] = mapped_column(Integer, nullable=False)
    review_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)
    canonical_publication_id: Mapped[int | None] = mapped_column(Integer)
    canonical_graph_result: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class ReasoningPublicationAttemptRow(Base):
    __tablename__ = "publication_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["publication_artifact_id"],
            ["reasoning_publication.publication_artifacts.publication_artifact_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("publication_artifact_id", "attempt_number"),
        Index(
            "idx_reasoning_publication_attempt",
            "publication_artifact_id",
            "attempt_number",
        ),
        {"schema": "reasoning_publication"},
    )
    attempt_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    publication_artifact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PublicationArtifactRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def locked_existing(
        self, artifact_hash: str
    ) -> ReasoningPublicationArtifactRow | None:
        return self.db.scalar(
            select(ReasoningPublicationArtifactRow)
            .where(ReasoningPublicationArtifactRow.artifact_hash == artifact_hash)
            .with_for_update()
        )

    def save_prepared(
        self, snapshot: dict[str, Any]
    ) -> ReasoningPublicationArtifactRow:
        existing = self.locked_existing(snapshot["artifact_hash"])
        if existing:
            return existing
        row = ReasoningPublicationArtifactRow(
            publication_artifact_id=snapshot["publication_artifact_id"],
            artifact_hash=snapshot["artifact_hash"],
            ledger_id=snapshot["ledger_id"],
            ledger_version=snapshot["ledger_version"],
            review_content_hash=snapshot["review_content_hash"],
            owner_subject=snapshot["owner_identity"],
            project_id=snapshot["project_id"],
            status="prepared",
            snapshot=snapshot,
        )
        self.db.add(row)
        self.db.flush()
        self.record_attempt(row, "PREPARED", snapshot["submitting_actor"], {})
        return row

    def record_attempt(
        self,
        row: ReasoningPublicationArtifactRow,
        outcome: str,
        actor: str,
        details: dict[str, Any],
    ) -> None:
        number = (
            self.db.query(ReasoningPublicationAttemptRow)
            .filter_by(publication_artifact_id=row.publication_artifact_id)
            .count()
            + 1
        )
        self.db.add(
            ReasoningPublicationAttemptRow(
                publication_artifact_id=row.publication_artifact_id,
                attempt_number=number,
                outcome=outcome,
                actor=actor,
                details=details,
            )
        )
        self.db.flush()

    def get(
        self, artifact_id: str, owner: str
    ) -> ReasoningPublicationArtifactRow | None:
        return self.db.scalar(
            select(ReasoningPublicationArtifactRow).where(
                ReasoningPublicationArtifactRow.publication_artifact_id == artifact_id,
                ReasoningPublicationArtifactRow.owner_subject == owner,
            )
        )

    def history(
        self, ledger_id: str, owner: str
    ) -> list[ReasoningPublicationArtifactRow]:
        return list(
            self.db.scalars(
                select(ReasoningPublicationArtifactRow)
                .where(
                    ReasoningPublicationArtifactRow.ledger_id == ledger_id,
                    ReasoningPublicationArtifactRow.owner_subject == owner,
                )
                .order_by(ReasoningPublicationArtifactRow.created_at)
            )
        )
