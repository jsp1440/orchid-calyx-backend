"""Persistence and routing for primary-source evidence already retrieved read-only.

Retrieval is intentionally separated from this module. This layer records a
source snapshot, preserves governance, and opens internal destination routes.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .primary_source import VERIFIER_VERSION, SourceSnapshot
from .repository import database_url


def _load_item(cur: Any, item_id: int, *, lock: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if lock else ""
    cur.execute(
        """
        SELECT id, domain, title, priority, lifecycle, knowledge_delta,
               verification_required, canonical_destinations, follow_up_tasks,
               source_urls, dois, canonical_promotion_prohibited,
               external_contact_prohibited
        FROM oc_intake.intelligence_items
        WHERE id=%s
        """ + suffix,
        (item_id,),
    )
    item = cur.fetchone()
    if not item:
        raise KeyError("INTELLIGENCE_ITEM_NOT_FOUND")
    if not item["canonical_promotion_prohibited"] or not item["external_contact_prohibited"]:
        raise RuntimeError("INTELLIGENCE_GOVERNANCE_NOT_FAIL_CLOSED")
    return item


def record_source_snapshot(item_id: int, snapshot: SourceSnapshot) -> dict[str, Any]:
    """Preserve primary-source metadata without promoting the scientific claim."""
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            item = _load_item(cur, item_id, lock=True)
            cur.execute(
                """
                INSERT INTO oc_intake.intelligence_verifications
                    (intelligence_item_id, source_url, resolved_url, source_kind, outcome,
                     http_status, content_type, source_title, source_doi, published_at,
                     authority_host, authority_tier, evidence_sha256, metadata,
                     verifier_version, canonical_promotion_performed, external_contact_performed)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NULLIF(%s,'')::timestamptz,%s,%s,%s,%s,%s,FALSE,FALSE)
                ON CONFLICT (intelligence_item_id, source_url, evidence_sha256) DO UPDATE SET
                    resolved_url=EXCLUDED.resolved_url,
                    outcome=EXCLUDED.outcome,
                    http_status=EXCLUDED.http_status,
                    content_type=EXCLUDED.content_type,
                    source_title=EXCLUDED.source_title,
                    source_doi=EXCLUDED.source_doi,
                    published_at=EXCLUDED.published_at,
                    authority_host=EXCLUDED.authority_host,
                    authority_tier=EXCLUDED.authority_tier,
                    metadata=EXCLUDED.metadata,
                    fetched_at=NOW()
                RETURNING *
                """,
                (
                    item_id,
                    snapshot.source_url,
                    snapshot.resolved_url,
                    snapshot.source_kind,
                    snapshot.outcome,
                    snapshot.http_status,
                    snapshot.content_type,
                    snapshot.source_title,
                    snapshot.source_doi,
                    snapshot.published_at,
                    snapshot.authority_host,
                    snapshot.authority_tier,
                    snapshot.evidence_sha256,
                    Jsonb(snapshot.metadata),
                    VERIFIER_VERSION,
                ),
            )
            verification = dict(cur.fetchone())
            source_confirmed = snapshot.outcome == "SOURCE_CONFIRMED"
            cur.execute(
                """
                UPDATE oc_intake.intelligence_items
                SET last_verified_at=NOW(), updated_at=NOW(),
                    lifecycle = CASE WHEN %s THEN 'NEEDS_REVIEW' ELSE lifecycle END,
                    verification_required=TRUE
                WHERE id=%s
                """,
                (source_confirmed, item_id),
            )
            cur.execute(
                """
                INSERT INTO oc_intake.intelligence_events
                    (intelligence_item_id, event_type, resulting_state, reason, actor, origin)
                VALUES (%s,'PRIMARY_SOURCE_RECORDED',%s,%s,%s,'AUTOMATED')
                """,
                (
                    item_id,
                    Jsonb({
                        "source_confirmed": source_confirmed,
                        "source_url": snapshot.source_url,
                        "resolved_url": snapshot.resolved_url,
                        "claim_verified": False,
                        "verification_required": True,
                        "canonical_graph_mutated": False,
                        "external_contacted": False,
                    }),
                    "Primary-source identity/evidence snapshot preserved; claim-level scientific verification remains review-gated.",
                    VERIFIER_VERSION,
                ),
            )
            if not source_confirmed:
                cur.execute(
                    """
                    INSERT INTO oc_intake.intelligence_actions
                        (intelligence_item_id, action_type, status, rationale, payload,
                         approval_required, external_side_effect)
                    VALUES (%s,'RESOLVE_SOURCE','OPEN',%s,%s,FALSE,FALSE)
                    ON CONFLICT (intelligence_item_id, action_type, destination) DO UPDATE SET
                        status='OPEN', rationale=EXCLUDED.rationale, payload=EXCLUDED.payload, updated_at=NOW()
                    """,
                    (
                        item_id,
                        "Primary source could not be confirmed; continue bounded source resolution.",
                        Jsonb({"title": item["title"], "source_url": snapshot.source_url}),
                    ),
                )
            return {
                "verification": verification,
                "source_confirmed": source_confirmed,
                "claim_verified": False,
                "verification_required": True,
                "canonical_graph_mutated": False,
                "external_contacted": False,
            }


def route_intelligence_item(item_id: int) -> dict[str, Any]:
    """Create internal routes only when at least one primary source is confirmed."""
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            item = _load_item(cur, item_id, lock=True)
            cur.execute(
                """
                SELECT count(*) AS n FROM oc_intake.intelligence_verifications
                WHERE intelligence_item_id=%s AND outcome='SOURCE_CONFIRMED'
                """,
                (item_id,),
            )
            confirmed = int(cur.fetchone()["n"])
            destinations = [str(value) for value in (item["canonical_destinations"] or [])]
            routes: list[dict[str, Any]] = []
            for destination in destinations:
                route_status = "READY" if confirmed else "BLOCKED"
                rationale = (
                    "Primary source confirmed; item is ready for the destination's governed intake/review queue."
                    if confirmed
                    else "No confirmed primary source; destination route remains blocked."
                )
                payload = {
                    "intelligence_item_id": item_id,
                    "domain": item["domain"],
                    "title": item["title"],
                    "priority": item["priority"],
                    "knowledge_delta": item["knowledge_delta"],
                    "source_confirmed": bool(confirmed),
                    "claim_verified": False,
                }
                cur.execute(
                    """
                    INSERT INTO oc_intake.intelligence_routes
                        (intelligence_item_id, destination, route_status, rationale, payload,
                         requires_human_approval, canonical_mutation_performed, external_contact_performed)
                    VALUES (%s,%s,%s,%s,%s,FALSE,FALSE,FALSE)
                    ON CONFLICT (intelligence_item_id, destination) DO UPDATE SET
                        route_status=EXCLUDED.route_status,
                        rationale=EXCLUDED.rationale,
                        payload=EXCLUDED.payload,
                        updated_at=NOW()
                    RETURNING id, destination, route_status, requires_human_approval,
                              canonical_mutation_performed, external_contact_performed
                    """,
                    (item_id, destination, route_status, rationale, Jsonb(payload)),
                )
                routes.append(dict(cur.fetchone()))

            if confirmed and destinations:
                cur.execute(
                    """
                    UPDATE oc_intake.intelligence_items
                    SET lifecycle='ROUTED', routed_at=NOW(), updated_at=NOW()
                    WHERE id=%s
                    """,
                    (item_id,),
                )
            cur.execute(
                """
                INSERT INTO oc_intake.intelligence_events
                    (intelligence_item_id, event_type, resulting_state, reason, actor, origin)
                VALUES (%s,'DOMAIN_ROUTED',%s,%s,'calyx-domain-router-v1','AUTOMATED')
                """,
                (
                    item_id,
                    Jsonb({"routes": routes, "claim_verified": False}),
                    "Internal routes created without canonical mutation or external side effects.",
                ),
            )
            return {
                "item_id": item_id,
                "routes": routes,
                "source_confirmed": bool(confirmed),
                "claim_verified": False,
                "canonical_graph_mutated": False,
                "external_contacted": False,
            }


def intelligence_operator_summary() -> dict[str, Any]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT lifecycle, knowledge_delta, count(*) AS count
                   FROM oc_intake.intelligence_items
                   GROUP BY lifecycle, knowledge_delta ORDER BY lifecycle, knowledge_delta"""
            )
            item_states = list(cur.fetchall())
            cur.execute(
                """SELECT destination, route_status, count(*) AS count
                   FROM oc_intake.intelligence_routes
                   GROUP BY destination, route_status ORDER BY destination, route_status"""
            )
            routes = list(cur.fetchall())
            cur.execute(
                """SELECT status, approval_required, count(*) AS count
                   FROM oc_intake.intelligence_actions
                   GROUP BY status, approval_required ORDER BY status, approval_required"""
            )
            actions = list(cur.fetchall())
            return {
                "item_states": item_states,
                "routes": routes,
                "actions": actions,
                "canonical_graph_mutated": False,
                "external_contacted": False,
            }
