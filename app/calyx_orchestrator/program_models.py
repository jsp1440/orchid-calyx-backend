from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

from .models import utcnow


class CalyxProgram(Base):
    __tablename__ = "calyx_engineering_programs"

    program_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    owner: Mapped[str] = mapped_column(String(240), index=True)
    title: Mapped[str] = mapped_column(String(240))
    objective: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    max_active_jobs: Mapped[int] = mapped_column(Integer, default=6)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CalyxProgramJob(Base):
    __tablename__ = "calyx_engineering_program_jobs"
    __table_args__ = (
        UniqueConstraint("program_id", "job_key", name="uq_calyx_program_job_key"),
        UniqueConstraint("program_id", "work_fingerprint", name="uq_calyx_program_work_fingerprint"),
    )

    program_job_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    program_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calyx_engineering_programs.program_id", ondelete="CASCADE"), index=True
    )
    orchestrator_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("calyx_orchestrator_jobs.job_id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_key: Mapped[str] = mapped_column(String(120))
    role_key: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(240))
    repository: Mapped[str] = mapped_column(String(240), index=True)
    branch: Mapped[str | None] = mapped_column(String(240), nullable=True, index=True)
    mutating: Mapped[bool] = mapped_column(Boolean, default=False)
    work_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="waiting", index=True)
    outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    blocker: Mapped[str | None] = mapped_column(Text, nullable=True)
    human_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CalyxProgramDependency(Base):
    __tablename__ = "calyx_engineering_program_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "program_id",
            "upstream_program_job_id",
            "downstream_program_job_id",
            name="uq_calyx_program_dependency",
        ),
    )

    dependency_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    program_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calyx_engineering_programs.program_id", ondelete="CASCADE"), index=True
    )
    upstream_program_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calyx_engineering_program_jobs.program_job_id", ondelete="CASCADE"), index=True
    )
    downstream_program_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calyx_engineering_program_jobs.program_job_id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
