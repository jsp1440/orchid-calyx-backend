"""Typed, versioned reasoning-ledger domain models.

Each ledger is an append-only record of reasoning entries attached to a
single tenant/project scope. Entries carry full provenance, uncertainty,
and conflict metadata. Publication is gated on explicit human approval and
passes structural validation. Private model chain-of-thought is explicitly
excluded.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID, uuid4


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LedgerError(Exception):
    """Base exception for reasoning-ledger failures."""


class LedgerValidationError(LedgerError, ValueError):
    """Raised when a ledger or entry violates a domain contract."""


class LedgerConflictError(LedgerError):
    """Raised when an operation would create an irreconcilable conflict."""


class LedgerPublicationError(LedgerError):
    """Raised when a ledger does not meet the publication gate requirements."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class LedgerEntryKind(str, Enum):
    """Canonical categories of reasoning entries in a ledger."""

    OBJECTIVE = "objective"
    SUPPORT = "support"
    COUNTEREVIDENCE = "counterevidence"
    ASSUMPTION = "assumption"
    CONFLICT = "conflict"
    CONCLUSION = "conclusion"
    REVIEW_DECISION = "review_decision"
    MEMORY_REF = "memory_ref"
    MODULE_DEF = "module_def"


class LedgerStatus(str, Enum):
    """Lifecycle states for a reasoning ledger."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    BLOCKED = "blocked"
    PUBLISHED = "published"


class ConflictState(str, Enum):
    """Resolution state of a conflict entry."""

    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"
    DEFERRED = "deferred"


class ReviewOutcome(str, Enum):
    """Decision made by a human reviewer."""

    APPROVED = "approved"
    REJECTED = "rejected"
    REQUIRES_REVISION = "requires_revision"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerProvenance:
    """Links an entry to its upstream sources across Orchid Continuum systems.

    All fields except ``source_kind`` and ``source_id`` are optional so that
    entries can link to a single system or to many simultaneously.
    """

    source_kind: str  # "literature", "concept", "rs_project", "dataset", "method",
    #                    "tool", "execution", "hash", or any extension value
    source_id: str
    literature_record_id: str | None = None
    concept_id: str | None = None
    rs_project_id: str | None = None
    dataset_id: str | None = None
    method_id: str | None = None
    tool_id: str | None = None
    execution_id: str | None = None
    content_hash: str | None = None  # SHA-256 hex of the referenced artifact
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    collector: str | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        source_kind = self.source_kind.strip()
        source_id = self.source_id.strip()
        if not source_kind:
            raise LedgerValidationError("provenance source_kind must not be empty")
        if not source_id:
            raise LedgerValidationError("provenance source_id must not be empty")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise LedgerValidationError("provenance retrieved_at must be timezone-aware")
        retrieved_at = self.retrieved_at.astimezone(timezone.utc)
        collector = self.collector.strip() if self.collector else None
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "source_id", source_id)
        object.__setattr__(self, "retrieved_at", retrieved_at)
        object.__setattr__(self, "collector", collector or None)
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))


# ---------------------------------------------------------------------------
# Uncertainty
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UncertaintyMarker:
    """Quantified uncertainty attached to a single ledger entry."""

    confidence: float  # [0, 1]
    rationale: str = ""
    unresolved_assumptions: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        confidence = float(self.confidence)
        if not 0.0 <= confidence <= 1.0:
            raise LedgerValidationError("uncertainty confidence must be in [0, 1]")
        rationale = self.rationale.strip()
        unresolved_assumptions = tuple(
            a.strip() for a in self.unresolved_assumptions if a.strip()
        )
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "unresolved_assumptions", unresolved_assumptions)

    @property
    def has_unresolved_assumptions(self) -> bool:
        return bool(self.unresolved_assumptions)


# ---------------------------------------------------------------------------
# Ledger entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """Single, immutable versioned entry in a reasoning ledger.

    Private model chain-of-thought must never be stored here; only
    externally verifiable reasoning that can be reviewed by a human.
    """

    entry_id: UUID = field(default_factory=uuid4)
    kind: LedgerEntryKind = LedgerEntryKind.OBJECTIVE
    version: int = 1
    sequence: int = 0  # monotone position within the ledger
    text: str = ""
    author: str = ""  # tenant-scoped user subject
    tenant_id: str = ""
    project_id: str = ""
    provenance: LedgerProvenance | None = None
    uncertainty: UncertaintyMarker | None = None
    conflict_state: ConflictState = ConflictState.UNRESOLVED
    references_entry_ids: tuple[UUID, ...] = field(default_factory=tuple)
    tags: tuple[str, ...] = field(default_factory=tuple)
    attributes: Mapping[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fingerprint: str = field(init=False)

    # Explicit exclusion flag — entries where this is True must never be
    # persisted or returned via any API.
    is_private_cot: bool = False

    def __post_init__(self) -> None:
        text = self.text.strip()
        author = self.author.strip()
        tenant_id = self.tenant_id.strip()
        project_id = self.project_id.strip()
        if not text:
            raise LedgerValidationError("ledger entry text must not be empty")
        if not author:
            raise LedgerValidationError("ledger entry author must not be empty")
        if not tenant_id:
            raise LedgerValidationError("ledger entry tenant_id must not be empty")
        if not project_id:
            raise LedgerValidationError("ledger entry project_id must not be empty")
        if self.version < 1:
            raise LedgerValidationError("ledger entry version must be >= 1")
        if self.sequence < 0:
            raise LedgerValidationError("ledger entry sequence must be >= 0")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise LedgerValidationError("ledger entry created_at must be timezone-aware")
        if self.is_private_cot:
            raise LedgerValidationError(
                "private model chain-of-thought entries must not be stored in the reasoning ledger"
            )
        if self.kind is LedgerEntryKind.CONFLICT and self.conflict_state is ConflictState.UNRESOLVED:
            # Conflict entries are allowed; validation happens at publication gate.
            pass
        if self.kind is LedgerEntryKind.REVIEW_DECISION:
            if "outcome" not in self.attributes:
                raise LedgerValidationError(
                    "review_decision entries must carry 'outcome' in attributes"
                )
        references_entry_ids = tuple(self.references_entry_ids)
        if len(set(references_entry_ids)) != len(references_entry_ids):
            raise LedgerValidationError("references_entry_ids must be unique")
        tags = tuple(t.strip() for t in self.tags if t.strip())
        created_at = self.created_at.astimezone(timezone.utc)

        payload = {
            "entry_id": str(self.entry_id),
            "kind": self.kind.value,
            "version": self.version,
            "sequence": self.sequence,
            "text": text,
            "author": author,
            "tenant_id": tenant_id,
            "project_id": project_id,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        object.__setattr__(self, "text", text)
        object.__setattr__(self, "author", author)
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "references_entry_ids", references_entry_ids)
        object.__setattr__(self, "tags", tags)
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "fingerprint", fingerprint)

    @property
    def is_resolved_conflict(self) -> bool:
        return (
            self.kind is LedgerEntryKind.CONFLICT
            and self.conflict_state is ConflictState.RESOLVED
        )


# ---------------------------------------------------------------------------
# Review decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    """Explicit human review decision attached to a reasoning ledger."""

    decision_id: UUID = field(default_factory=uuid4)
    reviewer: str = ""
    outcome: ReviewOutcome = ReviewOutcome.REQUIRES_REVISION
    rationale: str = ""
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ledger_version: int = 1

    def __post_init__(self) -> None:
        reviewer = self.reviewer.strip()
        rationale = self.rationale.strip()
        if not reviewer:
            raise LedgerValidationError("review decision reviewer must not be empty")
        if not rationale:
            raise LedgerValidationError("review decision rationale must not be empty")
        if self.ledger_version < 1:
            raise LedgerValidationError("review decision ledger_version must be >= 1")
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise LedgerValidationError("review decision decided_at must be timezone-aware")
        decided_at = self.decided_at.astimezone(timezone.utc)
        object.__setattr__(self, "reviewer", reviewer)
        object.__setattr__(self, "rationale", rationale)
        object.__setattr__(self, "decided_at", decided_at)


# ---------------------------------------------------------------------------
# Reasoning ledger
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReasoningLedger:
    """Append-only aggregate of typed reasoning entries for a single objective.

    Instances are immutable; new entries are added by creating a new ledger
    via :func:`ReasoningLedger.append`.

    Publication is possible only when:
    - status is APPROVED
    - there are no unresolved conflict entries
    - the conclusion confidence meets the minimum threshold
    - at least one REVIEW_DECISION with outcome APPROVED is present
    """

    ledger_id: UUID = field(default_factory=uuid4)
    tenant_id: str = ""
    project_id: str = ""
    title: str = ""
    description: str = ""
    status: LedgerStatus = LedgerStatus.DRAFT
    version: int = 1
    entries: tuple[LedgerEntry, ...] = field(default_factory=tuple)
    review_decisions: tuple[ReviewDecision, ...] = field(default_factory=tuple)
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ledger_fingerprint: str = field(init=False)

    MIN_PUBLICATION_CONFIDENCE: float = 0.6  # class-level constant

    def __post_init__(self) -> None:
        tenant_id = self.tenant_id.strip()
        project_id = self.project_id.strip()
        title = self.title.strip()
        created_by = self.created_by.strip()
        if not tenant_id:
            raise LedgerValidationError("reasoning ledger tenant_id must not be empty")
        if not project_id:
            raise LedgerValidationError("reasoning ledger project_id must not be empty")
        if not title:
            raise LedgerValidationError("reasoning ledger title must not be empty")
        if not created_by:
            raise LedgerValidationError("reasoning ledger created_by must not be empty")
        if self.version < 1:
            raise LedgerValidationError("reasoning ledger version must be >= 1")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise LedgerValidationError("reasoning ledger created_at must be timezone-aware")
        if self.updated_at.tzinfo is None or self.updated_at.utcoffset() is None:
            raise LedgerValidationError("reasoning ledger updated_at must be timezone-aware")

        entries = tuple(self.entries)
        for entry in entries:
            if entry.tenant_id != tenant_id or entry.project_id != project_id:
                raise LedgerValidationError(
                    "all ledger entries must share the ledger's tenant_id and project_id"
                )
        if len({e.entry_id for e in entries}) != len(entries):
            raise LedgerValidationError("ledger entries must have unique entry_id values")

        review_decisions = tuple(self.review_decisions)
        created_at = self.created_at.astimezone(timezone.utc)
        updated_at = self.updated_at.astimezone(timezone.utc)

        payload = {
            "ledger_id": str(self.ledger_id),
            "tenant_id": tenant_id,
            "project_id": project_id,
            "title": title,
            "version": self.version,
            "entry_fingerprints": [e.fingerprint for e in entries],
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        ledger_fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "created_by", created_by)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "review_decisions", review_decisions)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "ledger_fingerprint", ledger_fingerprint)

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def unresolved_conflicts(self) -> tuple[LedgerEntry, ...]:
        return tuple(
            e
            for e in self.entries
            if e.kind is LedgerEntryKind.CONFLICT
            and e.conflict_state is ConflictState.UNRESOLVED
        )

    @property
    def conclusion_entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(e for e in self.entries if e.kind is LedgerEntryKind.CONCLUSION)

    @property
    def min_conclusion_confidence(self) -> float:
        conclusions = self.conclusion_entries
        if not conclusions:
            return 0.0
        scored = [
            e.uncertainty.confidence
            for e in conclusions
            if e.uncertainty is not None
        ]
        return min(scored) if scored else 0.0

    @property
    def has_human_approval(self) -> bool:
        return any(
            d.outcome is ReviewOutcome.APPROVED for d in self.review_decisions
        )

    @property
    def is_publishable(self) -> bool:
        return (
            self.status is LedgerStatus.APPROVED
            and not self.unresolved_conflicts
            and self.min_conclusion_confidence >= self.MIN_PUBLICATION_CONFIDENCE
            and self.has_human_approval
        )

    # ------------------------------------------------------------------
    # Mutation helpers — return new immutable instances
    # ------------------------------------------------------------------

    def append(self, entry: LedgerEntry) -> "ReasoningLedger":
        """Return a new ledger with the entry appended and version incremented."""
        if entry.tenant_id != self.tenant_id or entry.project_id != self.project_id:
            raise LedgerValidationError(
                "appended entry must share the ledger's tenant_id and project_id"
            )
        if any(e.entry_id == entry.entry_id for e in self.entries):
            raise LedgerValidationError("entry_id already exists in ledger")
        now = datetime.now(timezone.utc)
        return ReasoningLedger(
            ledger_id=self.ledger_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            title=self.title,
            description=self.description,
            status=self.status,
            version=self.version + 1,
            entries=self.entries + (entry,),
            review_decisions=self.review_decisions,
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
        )

    def with_review(self, decision: ReviewDecision) -> "ReasoningLedger":
        """Return a new ledger with the review decision attached."""
        now = datetime.now(timezone.utc)
        new_status = (
            LedgerStatus.APPROVED
            if decision.outcome is ReviewOutcome.APPROVED
            else LedgerStatus.BLOCKED
            if decision.outcome is ReviewOutcome.REJECTED
            else LedgerStatus.IN_PROGRESS
        )
        return ReasoningLedger(
            ledger_id=self.ledger_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            title=self.title,
            description=self.description,
            status=new_status,
            version=self.version + 1,
            entries=self.entries,
            review_decisions=self.review_decisions + (decision,),
            created_by=self.created_by,
            created_at=self.created_at,
            updated_at=now,
        )
