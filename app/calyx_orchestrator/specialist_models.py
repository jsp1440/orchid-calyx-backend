from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

from .models import utcnow


class SpecialistMission(Base):
    __tablename__ = "calyx_specialist_missions"
    __table_args__ = (
        UniqueConstraint("owner", "idempotency_key", name="uq_specialist_mission_owner_idempotency"),
    )

    mission_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner: Mapped[str] = mapped_column(String(240), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(80), index=True)
    question: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    scientific: Mapped[bool] = mapped_column(Boolean, default=True)
    publication_candidate: Mapped[bool] = mapped_column(Boolean, default=False)
    automatic_publication: Mapped[bool] = mapped_column(Boolean, default=False)
    owner_approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    max_specialists: Mapped[int] = mapped_column(Integer, default=4)
    token_budget: Mapped[int] = mapped_column(Integer, default=100000)
    cost_budget_microusd: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_used_microusd: Mapped[int] = mapped_column(Integer, default=0)
    activation_json: Mapped[str] = mapped_column(Text)
    constraints_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SpecialistArtifact(Base):
    __tablename__ = "calyx_specialist_artifacts"
    __table_args__ = (
        UniqueConstraint("mission_id", "artifact_key", name="uq_specialist_artifact_mission_key"),
    )

    artifact_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    mission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calyx_specialist_missions.mission_id", ondelete="CASCADE"), index=True
    )
    artifact_key: Mapped[str] = mapped_column(String(160))
    specialist_id: Mapped[str] = mapped_column(String(80), index=True)
    artifact_type: Mapped[str] = mapped_column(String(80), index=True)
    content_json: Mapped[str] = mapped_column(Text)
    provenance_json: Mapped[str] = mapped_column(Text)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost_microusd: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpecialistReview(Base):
    __tablename__ = "calyx_specialist_reviews"
    __table_args__ = (
        UniqueConstraint("mission_id", "review_key", name="uq_specialist_review_mission_key"),
    )

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    mission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calyx_specialist_missions.mission_id", ondelete="CASCADE"), index=True
    )
    review_key: Mapped[str] = mapped_column(String(160))
    reviewer_id: Mapped[str] = mapped_column(String(80), default="scientific-reviewer")
    passed: Mapped[bool] = mapped_column(Boolean)
    findings_json: Mapped[str] = mapped_column(Text)
    provenance_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpecialistApproval(Base):
    __tablename__ = "calyx_specialist_approvals"
    __table_args__ = (
        UniqueConstraint("mission_id", "approval_key", name="uq_specialist_approval_mission_key"),
    )

    approval_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    mission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calyx_specialist_missions.mission_id", ondelete="CASCADE"), index=True
    )
    approval_key: Mapped[str] = mapped_column(String(160))
    actor: Mapped[str] = mapped_column(String(240))
    decision: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
