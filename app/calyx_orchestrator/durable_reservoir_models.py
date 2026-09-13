"""SQLAlchemy models for the durable autonomous research reservoir.

Two tables:
  calyx_reservoir_runs  — one row per AutonomousResearchRun invocation
  calyx_reservoir_tasks — one row per TaskLeaf per run

These back the DurableOrchestrate class, which provides the same public API as
DeepOrchestrate but persists every state transition to PostgreSQL (or SQLite in
tests), enabling restart recovery without data loss.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DurableReservoirRun(Base):
    """One row per autonomous research run."""

    __tablename__ = "calyx_reservoir_runs"

    run_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    blueprint_id: Mapped[str] = mapped_column(String(512), nullable=False, default="", index=True)
    run_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    proposed_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    configured_width: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    run_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="in_progress", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class DurableReservoirTask(Base):
    """One row per TaskLeaf per run.

    The (run_id, task_key) pair is unique — INSERT ... ON CONFLICT DO NOTHING makes
    enqueue_blueprint idempotent: re-enqueueing the same blueprint/run with the same
    keys is a no-op and never duplicates work.
    """

    __tablename__ = "calyx_reservoir_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "task_key", name="uq_calyx_reservoir_task_run_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(256),
        ForeignKey("calyx_reservoir_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_key: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    repo: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    module: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=2, index=True)
    authority_class: Mapped[str] = mapped_column(
        String(80), nullable=False, default="bounded_workspace_mutation"
    )
    consequence_risk: Mapped[str] = mapped_column(String(20), nullable=False, default="low")
    providers: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    estimated_size: Mapped[str] = mapped_column(String(4), nullable=False, default="m")
    dependencies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    acceptance_criteria: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    resources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Mutable execution state
    state: Mapped[str] = mapped_column(
        String(40), nullable=False, default="ready", index=True
    )
    leased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_holder: Mapped[str | None] = mapped_column(String(256), nullable=True)
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
