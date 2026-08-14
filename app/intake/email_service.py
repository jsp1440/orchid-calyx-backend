"""Application service for provenance-preserving external intelligence email intake."""

from __future__ import annotations

from typing import Any

from .extractor import content_hash, extract
from .intelligence import (
    assimilation_summary,
    canonical_email_text,
    intelligence_tasks,
    parse_external_intelligence,
)
from .intelligence_repository import record_intelligence_items
from .repository import create_source


def ingest_external_intelligence_email(
    *,
    subject: str,
    body: str,
    sender: str,
    message_id: str | None = None,
    received_at: str | None = None,
    imported_by: str | None = None,
) -> dict[str, Any]:
    """Ingest one email into the canonical intake + intelligence ledger pipeline."""
    canonical_content = canonical_email_text(
        sender=sender,
        subject=subject,
        body=body,
        message_id=message_id,
        received_at=received_at,
    )
    items = parse_external_intelligence(
        body,
        sender=sender,
        message_id=message_id or "",
    )
    result = extract(canonical_content)
    result.tasks.extend(intelligence_tasks(items))
    source = create_source(
        source_type="email",
        title=subject,
        content=canonical_content,
        content_hash=content_hash(canonical_content),
        source_url=None,
        imported_by=imported_by or "external-intelligence-email",
        extraction=result,
    )
    persisted = record_intelligence_items(
        source_id=source["id"],
        items=items,
        sender=sender,
        message_id=message_id,
    )
    return {
        **source,
        "intelligence": assimilation_summary(items),
        "intelligence_items": persisted,
        "external_contacted": False,
        "canonical_graph_mutated": False,
        "publication_performed": False,
    }
