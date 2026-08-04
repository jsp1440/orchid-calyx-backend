from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.types import JSON

from app.database import Base

from .models import ReasoningLedger
from .serialization import dict_to_ledger, ledger_to_canonical_json
from .service import LedgerNotFoundError, LedgerValidationError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StaleLedgerVersionError(LedgerValidationError):
    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"stale ledger version; current version is {current_version}")


class ReasoningLedgerHead(Base):
    __tablename__ = "ledger_heads"
    __table_args__ = (
        UniqueConstraint("owner_subject", "project_id", "logical_key_hash"),
        CheckConstraint("current_version >= 1"),
        Index("idx_reasoning_heads_owner_project", "owner_subject", "project_id"),
        {"schema": "reasoning_ledger"},
    )

    ledger_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(24), nullable=False)
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id", ondelete="RESTRICT"),
        nullable=False,
    )
    logical_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False)
    current_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ReasoningLedgerRevision(Base):
    __tablename__ = "ledger_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ledger_id"],
            ["reasoning_ledger.ledger_heads.ledger_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("ledger_id", "version"),
        CheckConstraint("version >= 1"),
        CheckConstraint("entry_count >= 0"),
        Index(
            "idx_reasoning_revisions_owner_project",
            "owner_subject",
            "project_id",
            "ledger_id",
            "version",
        ),
        {"schema": "reasoning_ledger"},
    )

    revision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ledger_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class ReasoningLedgerAuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["ledger_id", "ledger_version"],
            [
                "reasoning_ledger.ledger_revisions.ledger_id",
                "reasoning_ledger.ledger_revisions.version",
            ],
            ondelete="RESTRICT",
        ),
        Index(
            "idx_reasoning_audit_ledger", "ledger_id", "ledger_version", "occurred_at"
        ),
        {"schema": "reasoning_ledger"},
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ledger_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ledger_version: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_subject: Mapped[str] = mapped_column(Text, nullable=False)
    project_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("research_station.projects.project_id", ondelete="RESTRICT"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_subject: Mapped[str] = mapped_column(Text, nullable=False)
    event_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"), nullable=False, default=dict
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


TABLES = (
    ReasoningLedgerHead.__table__,
    ReasoningLedgerRevision.__table__,
    ReasoningLedgerAuditEvent.__table__,
)


def _payload(ledger: ReasoningLedger) -> tuple[dict[str, Any], str]:
    canonical = ledger_to_canonical_json(ledger)
    return json.loads(canonical), hashlib.sha256(canonical.encode()).hexdigest()


class SqlAlchemyReasoningLedgerRepository:
    """Revisioned repository; every mutation inserts a revision and audit event."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def _head(self, ledger_id: str, owner: str, *, lock: bool = False):
        statement = select(ReasoningLedgerHead).where(
            ReasoningLedgerHead.ledger_id == ledger_id,
            ReasoningLedgerHead.owner_subject == owner,
        )
        if lock:
            statement = statement.with_for_update()
        head = self.db.scalar(statement)
        if head is None:
            raise LedgerNotFoundError(f"ledger not found: {ledger_id}")
        return head

    def _revision(self, ledger_id: str, version: int) -> ReasoningLedgerRevision:
        revision = self.db.scalar(
            select(ReasoningLedgerRevision).where(
                ReasoningLedgerRevision.ledger_id == ledger_id,
                ReasoningLedgerRevision.version == version,
            )
        )
        if revision is None:
            raise LedgerNotFoundError(
                f"ledger revision not found: {ledger_id}@{version}"
            )
        return revision

    def create(
        self, ledger: ReasoningLedger, actor: str
    ) -> tuple[ReasoningLedger, bool]:
        ledger_id = str(ledger.ledger_id)
        existing = self.db.get(ReasoningLedgerHead, ledger_id)
        if existing is not None:
            if existing.owner_subject != ledger.tenant_id:
                raise LedgerNotFoundError(f"ledger not found: {ledger_id}")
            return self.current(ledger_id, ledger.tenant_id), False
        payload, content_hash = _payload(ledger)
        now = utcnow()
        logical_key = hashlib.sha256(
            f"{ledger.tenant_id}\0{ledger.project_id}\0{ledger.title}".encode()
        ).hexdigest()
        self.db.add(
            ReasoningLedgerHead(
                ledger_id=ledger_id,
                schema_version="calyx-reasoning-ledger/1",
                owner_subject=ledger.tenant_id,
                project_id=ledger.project_id,
                logical_key_hash=logical_key,
                current_version=ledger.version,
                current_content_hash=content_hash,
                created_at=now,
                updated_at=now,
            )
        )
        self._insert_revision(
            ledger, payload, content_hash, actor, "LEDGER_CREATED", {}
        )
        try:
            self.db.commit()
            return ledger, True
        except IntegrityError:
            self.db.rollback()
            existing = self.current(ledger_id, ledger.tenant_id)
            if (
                existing.project_id == ledger.project_id
                and existing.title == ledger.title
            ):
                return existing, False
            raise

    def _insert_revision(
        self,
        ledger: ReasoningLedger,
        payload: dict[str, Any],
        content_hash: str,
        actor: str,
        event_type: str,
        event_payload: dict[str, Any],
    ) -> None:
        now = utcnow()
        ledger_id = str(ledger.ledger_id)
        revision = ReasoningLedgerRevision(
            revision_id=str(uuid4()),
            ledger_id=ledger_id,
            version=ledger.version,
            owner_subject=ledger.tenant_id,
            project_id=ledger.project_id,
            status=ledger.status.value,
            entry_count=len(ledger.entries),
            content_hash=content_hash,
            canonical_payload=payload,
            created_at=now,
        )
        self.db.add(revision)
        # The audit row has a composite foreign key to this revision. There is no
        # ORM relationship between the mapped classes, so SQLAlchemy cannot infer
        # the required insertion order reliably. Flush the pending head/revision
        # before adding the dependent audit event.
        self.db.flush()
        self.db.add(
            ReasoningLedgerAuditEvent(
                event_id=str(uuid4()),
                ledger_id=ledger_id,
                ledger_version=ledger.version,
                owner_subject=ledger.tenant_id,
                project_id=ledger.project_id,
                event_type=event_type,
                actor_subject=actor,
                event_payload=event_payload,
                occurred_at=now,
            )
        )

    def mutate(
        self,
        ledger_id: str,
        owner: str,
        expected_version: int,
        actor: str,
        event_type: str,
        operation: Callable[[ReasoningLedger], ReasoningLedger],
        event_payload: dict[str, Any] | None = None,
    ) -> ReasoningLedger:
        try:
            head = self._head(ledger_id, owner, lock=True)
            if head.current_version != expected_version:
                raise StaleLedgerVersionError(head.current_version)
            current = dict_to_ledger(
                self._revision(ledger_id, head.current_version).canonical_payload
            )
            updated = operation(current)
            if updated.version != current.version + 1:
                raise LedgerValidationError(
                    "mutation must create exactly one new version"
                )
            payload, content_hash = _payload(updated)
            self._insert_revision(
                updated,
                payload,
                content_hash,
                actor,
                event_type,
                event_payload or {},
            )
            head.current_version = updated.version
            head.current_content_hash = content_hash
            head.updated_at = utcnow()
            self.db.commit()
            return updated
        except Exception:
            self.db.rollback()
            raise

    def mutate_once(
        self,
        ledger_id: str,
        owner: str,
        expected_version: int,
        actor: str,
        event_type: str,
        operation: Callable[[ReasoningLedger], ReasoningLedger],
        *,
        dedupe_attribute: str,
        dedupe_value: str,
        event_payload: dict[str, Any] | None = None,
    ) -> tuple[ReasoningLedger, bool]:
        """Apply one append-only mutation or reuse its existing artifact.

        Duplicate detection happens while the ledger head row is locked, so
        concurrent submissions cannot create two revisions for one inference.
        Version checking remains mandatory even for a duplicate retry.
        """
        try:
            head = self._head(ledger_id, owner, lock=True)
            if head.current_version != expected_version:
                raise StaleLedgerVersionError(head.current_version)
            current = dict_to_ledger(
                self._revision(ledger_id, head.current_version).canonical_payload
            )
            if any(
                str(entry.attributes.get(dedupe_attribute, "")) == dedupe_value
                for entry in current.entries
            ):
                self.db.commit()
                return current, False
            updated = operation(current)
            if updated.version != current.version + 1:
                raise LedgerValidationError(
                    "mutation must create exactly one new version"
                )
            payload, content_hash = _payload(updated)
            self._insert_revision(
                updated,
                payload,
                content_hash,
                actor,
                event_type,
                event_payload or {},
            )
            head.current_version = updated.version
            head.current_content_hash = content_hash
            head.updated_at = utcnow()
            self.db.commit()
            return updated, True
        except Exception:
            self.db.rollback()
            raise

    def current(self, ledger_id: str, owner: str) -> ReasoningLedger:
        head = self._head(ledger_id, owner)
        return dict_to_ledger(
            self._revision(ledger_id, head.current_version).canonical_payload
        )

    def history(self, ledger_id: str, owner: str) -> list[ReasoningLedger]:
        self._head(ledger_id, owner)
        rows = self.db.scalars(
            select(ReasoningLedgerRevision)
            .where(
                ReasoningLedgerRevision.ledger_id == ledger_id,
                ReasoningLedgerRevision.owner_subject == owner,
            )
            .order_by(ReasoningLedgerRevision.version)
        ).all()
        return [dict_to_ledger(row.canonical_payload) for row in rows]

    def audit_history(self, ledger_id: str, owner: str) -> list[dict[str, Any]]:
        self._head(ledger_id, owner)
        rows = self.db.scalars(
            select(ReasoningLedgerAuditEvent)
            .where(
                ReasoningLedgerAuditEvent.ledger_id == ledger_id,
                ReasoningLedgerAuditEvent.owner_subject == owner,
            )
            .order_by(
                ReasoningLedgerAuditEvent.ledger_version,
                ReasoningLedgerAuditEvent.occurred_at,
            )
        ).all()
        return [
            {
                "event_id": row.event_id,
                "ledger_version": row.ledger_version,
                "event_type": row.event_type,
                "actor_subject": row.actor_subject,
                "event_payload": row.event_payload,
                "occurred_at": row.occurred_at,
            }
            for row in rows
        ]

    def list_for_project(self, owner: str, project_id: str) -> list[ReasoningLedger]:
        heads = self.db.scalars(
            select(ReasoningLedgerHead)
            .where(
                ReasoningLedgerHead.owner_subject == owner,
                ReasoningLedgerHead.project_id == project_id,
            )
            .order_by(ReasoningLedgerHead.updated_at.desc())
        ).all()
        return [
            dict_to_ledger(
                self._revision(head.ledger_id, head.current_version).canonical_payload
            )
            for head in heads
        ]
