from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

from .models import utcnow


class SandboxValidationRequestRecord(Base):
    __tablename__ = "calyx_sandbox_validation_requests"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner: Mapped[str] = mapped_column(String(240), index=True)
    program_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    repository: Mapped[str] = mapped_column(String(240), index=True)
    branch: Mapped[str] = mapped_column(String(240), index=True)
    checkout_commit_sha: Mapped[str] = mapped_column(String(40))
    preset: Mapped[str] = mapped_column(String(20))
    targets_json: Mapped[str] = mapped_column(Text)
    timeout_seconds: Mapped[int] = mapped_column(Integer)
    request_digest: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    claim_worker: Mapped[str | None] = mapped_column(String(240), nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    authorization_id: Mapped[str | None] = mapped_column(String(240), nullable=True)
    policy_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evidence_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    receipt_digest: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
