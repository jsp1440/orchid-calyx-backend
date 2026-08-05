from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

OUTPUT_PATH = Path("calyx-eligible-ledger-discovery.json")


def _database_url() -> str:
    value = os.environ.get("DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    return value


def _approved_review(payload: dict[str, Any]) -> dict[str, Any] | None:
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


def discover() -> dict[str, Any]:
    engine = create_engine(_database_url(), pool_pre_ping=True)
    statement = text(
        """
        SELECT
            h.ledger_id,
            h.project_id::text AS project_id,
            h.owner_subject,
            h.current_version,
            h.current_content_hash,
            h.updated_at,
            r.status,
            r.canonical_payload
        FROM reasoning_ledger.ledger_heads AS h
        JOIN reasoning_ledger.ledger_revisions AS r
          ON r.ledger_id = h.ledger_id
         AND r.version = h.current_version
        WHERE r.status = 'approved'
        ORDER BY h.updated_at DESC, h.ledger_id ASC
        """
    )
    eligible: list[dict[str, Any]] = []
    approved_without_current_review: list[dict[str, Any]] = []
    with engine.connect() as connection:
        rows = connection.execute(statement).mappings().all()

    for row in rows:
        payload = row["canonical_payload"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        payload = dict(payload or {})
        review = _approved_review(payload)
        summary = {
            "ledger_id": str(row["ledger_id"]),
            "project_id": str(row["project_id"]),
            "title": str(payload.get("title") or ""),
            "version": int(row["current_version"]),
            "review_content_hash": str(payload.get("review_content_hash") or "").lower(),
            "current_content_hash": str(row["current_content_hash"]),
            "updated_at": row["updated_at"].astimezone(timezone.utc).isoformat(),
        }
        if review is None:
            approved_without_current_review.append(summary)
            continue
        summary["approved_review"] = review
        eligible.append(summary)

    result: dict[str, Any] = {
        "contract": "calyx-eligible-reasoning-ledger-discovery-v1",
        "captured_at": datetime.now(timezone.utc).isoformat(),
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
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"))
    result["artifact_hash"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return result


def main() -> int:
    result = discover()
    rendered = json.dumps(result, indent=2, sort_keys=True)
    OUTPUT_PATH.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if result["eligible_count"]:
        first = result["eligible_ledgers"][0]
        print("\nSELECTED_ELIGIBLE_LEDGER")
        print(f"ledger_id={first['ledger_id']}")
        print(f"version={first['version']}")
        print(f"review_content_hash={first['review_content_hash']}")
    else:
        print("\nNO_ELIGIBLE_REVIEWED_LEDGER_FOUND")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
