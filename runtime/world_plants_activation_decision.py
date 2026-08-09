"""Read-only World Plants/Hassler taxonomy activation decision packet.

This module summarizes durable staging evidence for owner review. It has no
activation, promotion, publication, deployment, or Knowledge Graph mutation
capability.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

CONTRACT_VERSION = "calyx-taxonomy-activation-decision/v1"


def _review_items(store: Any, release_id: str) -> list[dict[str, Any]]:
    with store.engine.connect() as connection:
        rows = (
            connection.execute(
                text(
                    "SELECT review_key, category, summary, evidence, status, updated_at "
                    "FROM taxonomy_pipeline.review_queue "
                    "WHERE release_id = :release_id "
                    "ORDER BY category, review_key"
                ),
                {"release_id": release_id},
            )
            .mappings()
            .all()
        )
    return [
        {
            "review_key": str(row["review_key"]),
            "category": str(row["category"]),
            "summary": str(row["summary"]),
            "evidence": dict(row["evidence"] or {}),
            "status": str(row["status"]),
            "updated_at": row["updated_at"].isoformat(),
        }
        for row in rows
    ]


def build_activation_decision_packet(store: Any, release_id: str) -> dict[str, Any]:
    release = store.get(release_id)
    if release is None:
        raise KeyError(f"taxonomy release not found: {release_id}")

    checkpoint = store.checkpoint(release_id)
    counts = store.counts(release_id)
    report = store.change_report(release_id)
    review_items = _review_items(store, release_id)

    snapshot = dict(release.get("snapshot") or {})
    expected_rows = int(snapshot.get("row_count") or 0)
    staged_rows = int(counts.get("staged") or 0)
    staging_complete = (
        bool(checkpoint.get("completed"))
        and expected_rows > 0
        and staged_rows == expected_rows
    )
    report_present = isinstance(report, dict)
    open_reviews = [item for item in review_items if item["status"] == "open"]
    disposition_reviews = [
        item for item in review_items if item["status"] in {"resolved", "dismissed"}
    ]

    blockers: list[str] = []
    if not staging_complete:
        blockers.append("STAGING_INCOMPLETE")
    if not report_present:
        blockers.append("CHANGE_REPORT_MISSING")
    if open_reviews:
        blockers.append("OPEN_TAXONOMY_REVIEW_ITEMS")
    if disposition_reviews:
        blockers.append("REVIEW_DISPOSITION_PROVENANCE_UNAVAILABLE")

    ready_for_owner_decision = not blockers
    decision_state = (
        "READY_FOR_OWNER_ACTIVATION_DECISION" if ready_for_owner_decision else "HOLD"
    )

    return {
        "contract": CONTRACT_VERSION,
        "release_id": release_id,
        "release_state": release.get("state"),
        "snapshot": snapshot,
        "checkpoint": checkpoint,
        "staging": {
            "expected_rows": expected_rows,
            "staged_rows": staged_rows,
            "complete": staging_complete,
        },
        "comparison": {
            "baseline_release_id": (
                report.get("baseline_release_id") if report_present else None
            ),
            "summary": (dict(report.get("summary") or {}) if report_present else None),
            "interpretation_note": (
                report.get("interpretation_note") if report_present else None
            ),
        },
        "review": {
            "items": review_items,
            "open_count": len(open_reviews),
            "disposition_without_durable_provenance_count": len(disposition_reviews),
            "durable_reviewer_identity_available": False,
            "durable_rationale_available": False,
            "note": (
                "Migration 107 records review status but not reviewer identity, rationale, "
                "decision timestamp, or evidence hash. Resolved/dismissed statuses therefore "
                "cannot by themselves satisfy scientific activation review."
            ),
        },
        "decision_state": decision_state,
        "blockers": blockers,
        "ready_for_owner_activation_decision": ready_for_owner_decision,
        "owner_approval_required": True,
        "activation_authorized": False,
        "activation_invoked": False,
        "automatic_promotion": False,
        "production_taxonomy_mutation_authorized": False,
        "knowledge_graph_mutation_authorized": False,
        "scientific_publication_authorized": False,
        "read_only": True,
    }
