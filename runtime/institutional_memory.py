"""Deterministic institutional-memory records for Calyx.

The core stores provenance-rich decisions and events as immutable values. It
contains no database, network, merge, deployment, publication, or external
communication behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, ClassVar


@dataclass(frozen=True)
class MemoryEvidence:
    source_type: str
    source_id: str
    source_url: str | None = None
    excerpt: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InstitutionalMemoryRecord:
    memory_id: str
    category: str
    title: str
    summary: str
    occurred_at: str
    actor: str
    evidence: tuple[MemoryEvidence, ...]
    related_ids: tuple[str, ...] = ()
    confidence: float = 1.0
    status: str = "active"

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "evidence": [item.as_dict() for item in self.evidence],
            "related_ids": list(self.related_ids),
        }


class InstitutionalMemoryRegistry:
    """Build and query immutable, provenance-backed memory records."""

    allowed_statuses: ClassVar[set[str]] = {"active", "superseded", "withdrawn"}

    def __init__(self) -> None:
        self._records: dict[str, InstitutionalMemoryRecord] = {}

    def create_record(
        self,
        *,
        category: str,
        title: str,
        summary: str,
        actor: str,
        evidence: tuple[MemoryEvidence, ...],
        occurred_at: str | None = None,
        related_ids: tuple[str, ...] = (),
        confidence: float = 1.0,
        status: str = "active",
    ) -> InstitutionalMemoryRecord:
        self._validate(category, title, summary, actor, evidence, confidence, status)
        timestamp = occurred_at or datetime.now(timezone.utc).isoformat()
        memory_id = self._memory_id(category, title, timestamp, evidence)
        record = InstitutionalMemoryRecord(
            memory_id=memory_id,
            category=category.strip().lower(),
            title=title.strip(),
            summary=summary.strip(),
            occurred_at=timestamp,
            actor=actor.strip(),
            evidence=evidence,
            related_ids=tuple(sorted(set(related_ids))),
            confidence=max(0.0, min(1.0, float(confidence))),
            status=status,
        )
        existing = self._records.get(memory_id)
        if existing is not None and existing != record:
            raise ValueError(f"memory id collision: {memory_id}")
        self._records[memory_id] = record
        return record

    def get(self, memory_id: str) -> InstitutionalMemoryRecord | None:
        return self._records.get(memory_id)

    def search(self, query: str) -> tuple[InstitutionalMemoryRecord, ...]:
        terms = tuple(part for part in query.lower().split() if part)
        if not terms:
            return ()
        ranked: list[tuple[int, str, InstitutionalMemoryRecord]] = []
        for record in self._records.values():
            haystack = (
                f"{record.category} {record.title} {record.summary} {record.actor}"
            ).lower()
            score = sum(term in haystack for term in terms)
            if score:
                ranked.append((-score, record.occurred_at, record))
        return tuple(item[2] for item in sorted(ranked))

    def timeline(self) -> tuple[InstitutionalMemoryRecord, ...]:
        return tuple(
            sorted(
                self._records.values(),
                key=lambda record: (record.occurred_at, record.memory_id),
            )
        )

    @classmethod
    def _validate(
        cls,
        category: str,
        title: str,
        summary: str,
        actor: str,
        evidence: tuple[MemoryEvidence, ...],
        confidence: float,
        status: str,
    ) -> None:
        if not all(value.strip() for value in (category, title, summary, actor)):
            raise ValueError("category, title, summary, and actor are required")
        if not evidence:
            raise ValueError("at least one evidence item is required")
        if not 0.0 <= float(confidence) <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if status not in cls.allowed_statuses:
            raise ValueError(f"unsupported memory status: {status}")
        for item in evidence:
            if not item.source_type.strip() or not item.source_id.strip():
                raise ValueError("evidence source_type and source_id are required")

    @staticmethod
    def _memory_id(
        category: str,
        title: str,
        occurred_at: str,
        evidence: tuple[MemoryEvidence, ...],
    ) -> str:
        source_ids = "|".join(sorted(item.source_id for item in evidence))
        payload = f"{category.strip().lower()}|{title.strip()}|{occurred_at}|{source_ids}"
        return f"mem-{sha256(payload.encode('utf-8')).hexdigest()[:20]}"
