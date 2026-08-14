from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

from .models import utcnow


class CalyxProgramValidationEvent(Base):
    __tablename__ = "calyx_program_validation_events"

    validation_event_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    program_job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("calyx_engineering_program_jobs.program_job_id", ondelete="CASCADE"),
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(Integer)
    disposition: Mapped[str] = mapped_column(String(40), index=True)
    code: Mapped[str] = mapped_column(String(160))
    feedback_json: Mapped[str] = mapped_column(Text, default="[]")
    receipt_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class CalyxBrainCompletionWriteback(Base):
    __tablename__ = "calyx_brain_completion_writebacks"
    __table_args__ = (
        UniqueConstraint("program_job_id", name="uq_calyx_brain_writeback_program_job"),
        UniqueConstraint("completion_key", name="uq_calyx_brain_writeback_completion_key"),
    )

    writeback_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    program_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calyx_engineering_programs.program_id", ondelete="CASCADE"), index=True
    )
    program_job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("calyx_engineering_program_jobs.program_job_id", ondelete="CASCADE"),
        index=True,
    )
    owner: Mapped[str] = mapped_column(String(240), index=True)
    completion_key: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="recorded", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
