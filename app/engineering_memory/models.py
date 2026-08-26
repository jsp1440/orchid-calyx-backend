"""SQLAlchemy models for Continuum Engineering Memory v1.

Three tables mirror the v1 data-model contract:

* ``engineering_memory_runs`` — a sanitized agent/task run outcome.
* ``engineering_memory_lessons`` — a distilled, provenance-bearing lesson.
* ``engineering_memory_retrievals`` — a retrieval event with feedback/telemetry.

Design constraints:

* Cross-dialect: JSON columns use ``JSON().with_variant(JSONB, "postgresql")``
  so the same models run on the SQLite test/dev fallback and on Postgres.
* Nullable numeric telemetry columns deliberately distinguish *measured zero*
  from *unavailable* (``NULL``).  Never coalesce unavailable to zero.
* Every table carries ``workspace_scope`` so reads/writes are tenant-isolated.
* ``evidence_class`` is fixed to ``non_scientific_evidence``; a CHECK constraint
  enforces it at the database layer as a defence in depth.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.types import JSON

from app.database import Base

# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

#: Engineering memory is never scientific evidence.  This value is fixed and
#: enforced by both the service layer and a database CHECK constraint.
EVIDENCE_CLASS_NON_SCIENTIFIC = "non_scientific_evidence"

#: Allowed engineering data classifications.  Writes fail closed on any other.
DATA_CLASSIFICATIONS: tuple[str, ...] = (
    "public_engineering",
    "internal_engineering",
    "restricted_engineering",
)

#: Redaction states persisted alongside every stored payload.
REDACTION_CLEAN = "clean"  # nothing matched a redaction rule
REDACTION_REDACTED = "redacted"  # one or more redactions were applied
REDACTION_STATES: tuple[str, ...] = (REDACTION_CLEAN, REDACTION_REDACTED)

#: Run outcomes.
RUN_OUTCOMES: tuple[str, ...] = ("success", "failure", "partial")

#: Lesson lifecycle states.  Only ``candidate`` and ``verified`` are returnable.
LESSON_CANDIDATE = "candidate"
LESSON_VERIFIED = "verified"
LESSON_INVALIDATED = "invalidated"
LESSON_EXPIRED = "expired"
LESSON_STATUSES: tuple[str, ...] = (
    LESSON_CANDIDATE,
    LESSON_VERIFIED,
    LESSON_INVALIDATED,
    LESSON_EXPIRED,
)
#: Lesson statuses excluded from retrieval by default.
NON_RETURNABLE_STATUSES: frozenset[str] = frozenset(
    {LESSON_INVALIDATED, LESSON_EXPIRED}
)

#: Verification states independent of lifecycle status.
VERIFICATION_UNVERIFIED = "unverified"
VERIFICATION_VERIFIED = "verified"
VERIFICATION_REFUTED = "refuted"
VERIFICATION_STATES: tuple[str, ...] = (
    VERIFICATION_UNVERIFIED,
    VERIFICATION_VERIFIED,
    VERIFICATION_REFUTED,
)

#: Trust/confidence bands.
CONFIDENCE_BANDS: tuple[str, ...] = ("low", "medium", "high")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


def _json():
    """A JSON column that upgrades to JSONB on PostgreSQL."""
    return JSON().with_variant(JSONB, "postgresql")


_EVIDENCE_CLASS_CHECK = CheckConstraint(
    f"evidence_class = '{EVIDENCE_CLASS_NON_SCIENTIFIC}'",
    name="%(table_name)s_evidence_class_non_scientific",
)


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class EngineeringMemoryRun(Base):
    """A sanitized outcome of an agent/task run.

    Raw prompts and full conversations are intentionally *not* stored.  Only a
    bounded, redacted ``sanitized_summary`` is retained.
    """

    __tablename__ = "engineering_memory_runs"
    __table_args__ = (
        _EVIDENCE_CLASS_CHECK,
        CheckConstraint(
            "redaction_status IN ('clean','redacted')",
            name="engineering_memory_runs_redaction_status_valid",
        ),
        CheckConstraint(
            "outcome IN ('success','failure','partial')",
            name="engineering_memory_runs_outcome_valid",
        ),
        Index("idx_eng_mem_runs_scope", "workspace_scope"),
        Index("idx_eng_mem_runs_scope_repo", "workspace_scope", "repository"),
    )

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)

    # Provenance / identity.
    executor: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    workspace_scope: Mapped[str] = mapped_column(String(240), index=True)
    repository: Mapped[str] = mapped_column(String(240))
    branch: Mapped[str | None] = mapped_column(String(240), nullable=True)
    task_ref: Mapped[str | None] = mapped_column(String(240), nullable=True)
    issue_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pr_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    commit_shas: Mapped[list] = mapped_column(_json(), default=list)

    # Outcome.
    outcome: Mapped[str] = mapped_column(String(20))
    checks: Mapped[dict] = mapped_column(_json(), default=dict)
    sanitized_summary: Mapped[str] = mapped_column(Text, default="")

    # Bounded telemetry.  NULL == unavailable, 0 == measured zero.
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Governance.
    data_classification: Mapped[str] = mapped_column(String(40))
    evidence_class: Mapped[str] = mapped_column(
        String(40), default=EVIDENCE_CLASS_NON_SCIENTIFIC
    )
    redaction_status: Mapped[str] = mapped_column(String(20))
    redaction_report: Mapped[dict] = mapped_column(_json(), default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class EngineeringMemoryLesson(Base):
    """A distilled, provenance-bearing engineering lesson."""

    __tablename__ = "engineering_memory_lessons"
    __table_args__ = (
        _EVIDENCE_CLASS_CHECK,
        CheckConstraint(
            "status IN ('candidate','verified','invalidated','expired')",
            name="engineering_memory_lessons_status_valid",
        ),
        CheckConstraint(
            "verification_status IN ('unverified','verified','refuted')",
            name="engineering_memory_lessons_verification_valid",
        ),
        CheckConstraint(
            "redaction_status IN ('clean','redacted')",
            name="engineering_memory_lessons_redaction_status_valid",
        ),
        Index("idx_eng_mem_lessons_scope_status", "workspace_scope", "status"),
        Index("idx_eng_mem_lessons_scope_module", "workspace_scope", "module"),
    )

    lesson_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_id
    )

    # Scope.
    workspace_scope: Mapped[str] = mapped_column(String(240), index=True)
    repository: Mapped[str] = mapped_column(String(240))
    module: Mapped[str | None] = mapped_column(String(240), nullable=True)

    # Content.
    problem: Mapped[str] = mapped_column(Text)
    cause: Mapped[str] = mapped_column(Text, default="")
    solution: Mapped[str] = mapped_column(Text)
    applicability: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(_json(), default=list)

    # Lexical + optional semantic search representations.
    lexical_document: Mapped[str] = mapped_column(Text, default="")
    embedding: Mapped[list | None] = mapped_column(_json(), nullable=True)

    # Provenance.
    source_run_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("engineering_memory_runs.run_id"),
        nullable=True,
    )
    github_provenance: Mapped[dict] = mapped_column(_json(), default=dict)

    # Verification / trust.
    status: Mapped[str] = mapped_column(String(20), default=LESSON_CANDIDATE)
    verification_status: Mapped[str] = mapped_column(
        String(20), default=VERIFICATION_UNVERIFIED
    )
    verification_evidence: Mapped[dict] = mapped_column(_json(), default=dict)
    confidence: Mapped[str] = mapped_column(String(20), default="low")
    invalidated_reason: Mapped[str | None] = mapped_column(String(240), nullable=True)

    # Deterministic invalidation fingerprints.
    dependency_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    file_fingerprints: Mapped[dict] = mapped_column(_json(), default=dict)

    # Governance.
    data_classification: Mapped[str] = mapped_column(String(40))
    evidence_class: Mapped[str] = mapped_column(
        String(40), default=EVIDENCE_CLASS_NON_SCIENTIFIC
    )
    redaction_status: Mapped[str] = mapped_column(String(20))
    redaction_report: Mapped[dict] = mapped_column(_json(), default=dict)

    # Lifecycle.
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class EngineeringMemoryRetrieval(Base):
    """A retrieval event, its results, feedback, and usage telemetry."""

    __tablename__ = "engineering_memory_retrievals"
    __table_args__ = (
        Index("idx_eng_mem_retrievals_scope", "workspace_scope"),
    )

    retrieval_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_new_id
    )

    # Scope + query.
    workspace_scope: Mapped[str] = mapped_column(String(240), index=True)
    repository: Mapped[str] = mapped_column(String(240))
    module: Mapped[str | None] = mapped_column(String(240), nullable=True)
    query_text: Mapped[str] = mapped_column(Text)

    # Results: [{lesson_id, rank, score, verification_status, status}, ...]
    retrieved: Mapped[list] = mapped_column(_json(), default=list)
    injected: Mapped[bool] = mapped_column(Boolean, default=False)
    injected_char_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    injected_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Feedback.  NULL == not yet recorded.
    feedback: Mapped[str | None] = mapped_column(String(20), nullable=True)
    feedback_outcome: Mapped[dict | None] = mapped_column(_json(), nullable=True)

    # Telemetry.  NULL == unavailable, 0 == measured zero.
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_tokens_saved: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


#: Convenience export of the three tables for scoped ``create_all`` in tests.
TABLES = (
    EngineeringMemoryRun.__table__,
    EngineeringMemoryLesson.__table__,
    EngineeringMemoryRetrieval.__table__,
)
