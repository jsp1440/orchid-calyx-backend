"""Canonical serialization for reasoning-ledger objects.

All serialization is deterministic: identical inputs always produce
identical JSON bytes (sort_keys=True, no trailing whitespace, UTC datetimes).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from .models import (
    ConflictDisposition,
    ConflictDispositionType,
    ConflictState,
    LedgerEntry,
    LedgerEntryKind,
    LedgerProvenance,
    LedgerStatus,
    ReasoningLedger,
    ReviewDecision,
    ReviewOutcome,
    UncertaintyMarker,
)


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _uuid(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def provenance_to_dict(p: LedgerProvenance) -> dict[str, Any]:
    return {
        "source_kind": p.source_kind,
        "source_id": p.source_id,
        "literature_record_id": p.literature_record_id,
        "concept_id": p.concept_id,
        "rs_project_id": p.rs_project_id,
        "dataset_id": p.dataset_id,
        "method_id": p.method_id,
        "tool_id": p.tool_id,
        "execution_id": p.execution_id,
        "content_hash": p.content_hash,
        "retrieved_at": _dt(p.retrieved_at),
        "collector": p.collector,
        "extra": dict(p.extra),
    }


def uncertainty_to_dict(u: UncertaintyMarker) -> dict[str, Any]:
    return {
        "confidence": u.confidence,
        "rationale": u.rationale,
        "unresolved_assumptions": list(u.unresolved_assumptions),
    }


def entry_to_dict(e: LedgerEntry) -> dict[str, Any]:
    return {
        "entry_id": _uuid(e.entry_id),
        "kind": e.kind.value,
        "version": e.version,
        "sequence": e.sequence,
        "text": e.text,
        "author": e.author,
        "tenant_id": e.tenant_id,
        "project_id": e.project_id,
        "provenance": provenance_to_dict(e.provenance) if e.provenance else None,
        "uncertainty": uncertainty_to_dict(e.uncertainty) if e.uncertainty else None,
        "conflict_state": e.conflict_state.value,
        "references_entry_ids": [str(r) for r in e.references_entry_ids],
        "tags": list(e.tags),
        "attributes": dict(e.attributes),
        "created_at": _dt(e.created_at),
        "fingerprint": e.fingerprint,
    }


def review_decision_to_dict(d: ReviewDecision) -> dict[str, Any]:
    return {
        "decision_id": _uuid(d.decision_id),
        "reviewer": d.reviewer,
        "outcome": d.outcome.value,
        "rationale": d.rationale,
        "decided_at": _dt(d.decided_at),
        "ledger_version": d.ledger_version,
        "reviewed_content_hash": d.reviewed_content_hash,
    }


def conflict_disposition_to_dict(d: ConflictDisposition) -> dict[str, Any]:
    return {
        "conflict_entry_id": _uuid(d.conflict_entry_id),
        "disposition": d.disposition.value,
        "rationale": d.rationale,
        "actor": d.actor,
        "effective_at": _dt(d.effective_at),
        "effective_ledger_version": d.effective_ledger_version,
    }


def ledger_to_dict(ledger: ReasoningLedger) -> dict[str, Any]:
    return {
        "ledger_id": _uuid(ledger.ledger_id),
        "tenant_id": ledger.tenant_id,
        "project_id": ledger.project_id,
        "title": ledger.title,
        "description": ledger.description,
        "status": ledger.status.value,
        "version": ledger.version,
        "entries": [entry_to_dict(e) for e in ledger.entries],
        "review_decisions": [
            review_decision_to_dict(d) for d in ledger.review_decisions
        ],
        "conflict_dispositions": [
            conflict_disposition_to_dict(d) for d in ledger.conflict_dispositions
        ],
        "resolved_conflict_ids": sorted(
            str(identifier) for identifier in ledger.resolved_conflict_ids
        ),
        "created_by": ledger.created_by,
        "created_at": _dt(ledger.created_at),
        "updated_at": _dt(ledger.updated_at),
        "ledger_fingerprint": ledger.ledger_fingerprint,
        "review_content_hash": ledger.review_content_hash,
    }


def ledger_to_canonical_json(ledger: ReasoningLedger) -> str:
    """Produce deterministic JSON bytes for a reasoning ledger."""
    return json.dumps(ledger_to_dict(ledger), sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Deserialization helpers
# ---------------------------------------------------------------------------


def dict_to_provenance(d: dict[str, Any]) -> LedgerProvenance:
    from datetime import datetime as _dt_cls
    from datetime import timezone

    retrieved_at_raw = d.get("retrieved_at")
    retrieved_at = (
        _dt_cls.fromisoformat(retrieved_at_raw).astimezone(timezone.utc)
        if retrieved_at_raw
        else datetime.now(timezone.utc)
    )
    return LedgerProvenance(
        source_kind=d["source_kind"],
        source_id=d["source_id"],
        literature_record_id=d.get("literature_record_id"),
        concept_id=d.get("concept_id"),
        rs_project_id=d.get("rs_project_id"),
        dataset_id=d.get("dataset_id"),
        method_id=d.get("method_id"),
        tool_id=d.get("tool_id"),
        execution_id=d.get("execution_id"),
        content_hash=d.get("content_hash"),
        retrieved_at=retrieved_at,
        collector=d.get("collector"),
        extra=d.get("extra", {}),
    )


def dict_to_uncertainty(d: dict[str, Any]) -> UncertaintyMarker:
    return UncertaintyMarker(
        confidence=float(d["confidence"]),
        rationale=d.get("rationale", ""),
        unresolved_assumptions=tuple(d.get("unresolved_assumptions", [])),
    )


def dict_to_entry(d: dict[str, Any]) -> LedgerEntry:
    from datetime import datetime as _dt_cls
    from datetime import timezone

    created_at_raw = d.get("created_at")
    created_at = (
        _dt_cls.fromisoformat(created_at_raw).astimezone(timezone.utc)
        if created_at_raw
        else datetime.now(timezone.utc)
    )
    provenance = dict_to_provenance(d["provenance"]) if d.get("provenance") else None
    uncertainty = (
        dict_to_uncertainty(d["uncertainty"]) if d.get("uncertainty") else None
    )
    return LedgerEntry(
        entry_id=UUID(d["entry_id"]),
        kind=LedgerEntryKind(d["kind"]),
        version=int(d.get("version", 1)),
        sequence=int(d.get("sequence", 0)),
        text=d["text"],
        author=d["author"],
        tenant_id=d["tenant_id"],
        project_id=d["project_id"],
        provenance=provenance,
        uncertainty=uncertainty,
        conflict_state=ConflictState(
            d.get("conflict_state", ConflictState.UNRESOLVED.value)
        ),
        references_entry_ids=tuple(UUID(r) for r in d.get("references_entry_ids", [])),
        tags=tuple(d.get("tags", [])),
        attributes=d.get("attributes", {}),
        created_at=created_at,
    )


def dict_to_review_decision(d: dict[str, Any]) -> ReviewDecision:
    from datetime import datetime as _dt_cls
    from datetime import timezone

    decided_at_raw = d.get("decided_at")
    decided_at = (
        _dt_cls.fromisoformat(decided_at_raw).astimezone(timezone.utc)
        if decided_at_raw
        else datetime.now(timezone.utc)
    )
    return ReviewDecision(
        decision_id=UUID(d["decision_id"]),
        reviewer=d["reviewer"],
        outcome=ReviewOutcome(d["outcome"]),
        rationale=d["rationale"],
        decided_at=decided_at,
        ledger_version=int(d.get("ledger_version", 1)),
        reviewed_content_hash=d.get("reviewed_content_hash", ""),
    )


def dict_to_conflict_disposition(d: dict[str, Any]) -> ConflictDisposition:
    from datetime import datetime as _dt_cls
    from datetime import timezone

    return ConflictDisposition(
        conflict_entry_id=UUID(d["conflict_entry_id"]),
        disposition=ConflictDispositionType(d["disposition"]),
        rationale=d["rationale"],
        actor=d["actor"],
        effective_at=_dt_cls.fromisoformat(d["effective_at"]).astimezone(timezone.utc),
        effective_ledger_version=int(d["effective_ledger_version"]),
    )


def dict_to_ledger(d: dict[str, Any]) -> ReasoningLedger:
    from datetime import datetime as _dt_cls
    from datetime import timezone

    created_at = _dt_cls.fromisoformat(d["created_at"]).astimezone(timezone.utc)
    updated_at = _dt_cls.fromisoformat(d["updated_at"]).astimezone(timezone.utc)
    return ReasoningLedger(
        ledger_id=UUID(d["ledger_id"]),
        tenant_id=d["tenant_id"],
        project_id=d["project_id"],
        title=d["title"],
        description=d.get("description", ""),
        status=LedgerStatus(d["status"]),
        version=int(d["version"]),
        entries=tuple(dict_to_entry(e) for e in d.get("entries", [])),
        review_decisions=tuple(
            dict_to_review_decision(r) for r in d.get("review_decisions", [])
        ),
        conflict_dispositions=tuple(
            dict_to_conflict_disposition(item)
            for item in d.get("conflict_dispositions", [])
        ),
        resolved_conflict_ids=frozenset(
            UUID(identifier) for identifier in d.get("resolved_conflict_ids", [])
        ),
        created_by=d["created_by"],
        created_at=created_at,
        updated_at=updated_at,
    )
