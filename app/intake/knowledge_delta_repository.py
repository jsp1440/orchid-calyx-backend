"""State transition persistence for read-only knowledge-delta comparisons."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .knowledge_delta import KnowledgeDeltaAssessment
from .repository import database_url


_ALLOWED_COMPARISON_DELTAS = {"ALREADY_KNOWN", "REQUIRES_REVIEW"}


def record_comparison(assessment: KnowledgeDeltaAssessment, *, actor: str = "calyx-knowledge-delta-v1") -> dict[str, Any]:
    """Record a comparison result without advancing verification or publication.

    The comparator is intentionally permitted to write only ALREADY_KNOWN or
    REQUIRES_REVIEW. Candidate novelty labels live in the audit event until a
    primary-source verification step proves them.
    """
    if assessment.knowledge_delta not in _ALLOWED_COMPARISON_DELTAS:
        raise ValueError("UNVERIFIED_DELTA_PROMOTION_PROHIBITED")

    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, lifecycle, knowledge_delta, verification_required,
                       canonical_promotion_prohibited, external_contact_prohibited
                FROM oc_intake.intelligence_items
                WHERE id=%s
                FOR UPDATE
                """,
                (assessment.item_id,),
            )
            previous = cur.fetchone()
            if not previous:
                raise KeyError("INTELLIGENCE_ITEM_NOT_FOUND")
            if not previous["canonical_promotion_prohibited"] or not previous["external_contact_prohibited"]:
                raise RuntimeError("INTELLIGENCE_GOVERNANCE_NOT_FAIL_CLOSED")

            resulting = {
                "lifecycle": "COMPARED",
                "knowledge_delta": assessment.knowledge_delta,
                "candidate_delta": assessment.candidate_delta,
                "verification_required": True,
                "confidence": assessment.confidence,
                "stores_checked": list(assessment.stores_checked),
                "matches": list(assessment.matches),
                "canonical_graph_mutated": False,
                "external_contacted": False,
            }
            cur.execute(
                """
                UPDATE oc_intake.intelligence_items
                SET lifecycle='COMPARED', knowledge_delta=%s,
                    verification_required=TRUE, last_compared_at=NOW(), updated_at=NOW()
                WHERE id=%s
                RETURNING id, lifecycle, knowledge_delta, verification_required,
                          last_compared_at, canonical_promotion_prohibited,
                          external_contact_prohibited
                """,
                (assessment.knowledge_delta, assessment.item_id),
            )
            updated = cur.fetchone()
            cur.execute(
                """
                INSERT INTO oc_intake.intelligence_events
                    (intelligence_item_id, event_type, previous_state, resulting_state,
                     reason, actor, origin)
                VALUES (%s,'KNOWLEDGE_COMPARED',%s,%s,%s,%s,'AUTOMATED')
                """,
                (
                    assessment.item_id,
                    Jsonb(dict(previous)),
                    Jsonb(resulting),
                    assessment.reason,
                    actor,
                ),
            )
            return {
                **updated,
                "candidate_delta": assessment.candidate_delta,
                "confidence": assessment.confidence,
                "matches": list(assessment.matches),
                "stores_checked": list(assessment.stores_checked),
                "canonical_graph_mutated": False,
                "external_contacted": False,
            }
