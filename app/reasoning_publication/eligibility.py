from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


def approved_current_review(payload: dict[str, Any]) -> dict[str, Any] | None:
    version = int(payload.get("version") or 0)
    review_hash = str(payload.get("review_content_hash") or "").lower()
    for decision in reversed(payload.get("review_decisions") or []):
        outcome = str(decision.get("outcome") or "").lower()
        decision_version = int(decision.get("ledger_version") or 0)
        reviewed_hash = str(decision.get("reviewed_content_hash") or "").lower()
        if (
            outcome == "approved"
            and decision_version == version
            and len(reviewed_hash) == 64
            and reviewed_hash == review_hash
        ):
            return {
                "decision_id": str(decision.get("decision_id") or ""),
                "reviewer": str(decision.get("reviewer") or ""),
                "decided_at": decision.get("decided_at"),
                "reviewed_content_hash": reviewed_hash,
            }
    return None


def discover_eligible_ledgers(db: Session, owner: str) -> dict[str, Any]:
    """Read-only owner-scoped current-version publication eligibility discovery."""
    rows = (
        db.execute(
            text(
                """
                SELECT
                    h.ledger_id,
                    h.project_id::text AS project_id,
                    h.current_version,
                    h.current_content_hash,
                    h.updated_at,
                    r.canonical_payload
                FROM reasoning_ledger.ledger_heads AS h
                JOIN reasoning_ledger.ledger_revisions AS r
                  ON r.ledger_id = h.ledger_id
                 AND r.version = h.current_version
                WHERE h.owner_subject = :owner
                  AND r.status = 'approved'
                ORDER BY h.updated_at DESC, h.ledger_id ASC
                """
            ),
            {"owner": owner},
        )
        .mappings()
        .all()
    )
    eligible: list[dict[str, Any]] = []
    approved_without_current_review: list[dict[str, Any]] = []
    for row in rows:
        payload = row["canonical_payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload = dict(payload or {})
        summary = {
            "ledger_id": str(row["ledger_id"]),
            "project_id": str(row["project_id"]),
            "title": str(payload.get("title") or ""),
            "version": int(row["current_version"]),
            "review_content_hash": str(
                payload.get("review_content_hash") or ""
            ).lower(),
            "current_content_hash": str(row["current_content_hash"]),
            "updated_at": row["updated_at"].isoformat(),
        }
        review = approved_current_review(payload)
        if review is None:
            approved_without_current_review.append(summary)
        else:
            summary["approved_review"] = review
            eligible.append(summary)
    return {
        "contract": "calyx-eligible-reasoning-ledger-discovery-v1",
        "result": "ELIGIBLE_LEDGER_FOUND" if eligible else "NO_ELIGIBLE_LEDGER",
        "read_only": True,
        "eligible_count": len(eligible),
        "eligible_ledgers": eligible,
        "approved_but_not_currently_reviewed_count": len(
            approved_without_current_review
        ),
        "approved_but_not_currently_reviewed": approved_without_current_review,
        "production_mutation": False,
        "publication_endpoint_invoked": False,
    }
