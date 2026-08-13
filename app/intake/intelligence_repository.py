"""Durable persistence for external-intelligence items and observations."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .repository import database_url


def record_intelligence_items(
    *,
    source_id: int,
    items: list[dict[str, object]],
    sender: str | None = None,
    message_id: str | None = None,
) -> list[dict[str, Any]]:
    """Upsert canonical items and append idempotent source observations.

    Repeated briefings update last_seen_at and preserve each distinct source
    observation. Canonical scientific promotion remains prohibited here.
    """
    recorded: list[dict[str, Any]] = []
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for item in items:
                fingerprint = str(item["knowledge_fingerprint"])
                cur.execute(
                    """
                    INSERT INTO oc_intake.intelligence_items
                        (knowledge_fingerprint, domain, title, normalized_title, current_detail,
                         priority, lifecycle, knowledge_delta, verification_required,
                         canonical_destinations, follow_up_tasks, source_urls, dois,
                         observation_count, canonical_promotion_prohibited, external_contact_prohibited)
                    VALUES
                        (%s,%s,%s,%s,%s,%s,'DISCOVERED','UNASSESSED',TRUE,%s,%s,%s,%s,0,TRUE,TRUE)
                    ON CONFLICT (knowledge_fingerprint) DO UPDATE SET
                        title = EXCLUDED.title,
                        normalized_title = EXCLUDED.normalized_title,
                        current_detail = EXCLUDED.current_detail,
                        priority = CASE
                            WHEN oc_intake.intelligence_items.priority = 'CRITICAL' THEN 'CRITICAL'
                            WHEN EXCLUDED.priority = 'CRITICAL' THEN 'CRITICAL'
                            WHEN oc_intake.intelligence_items.priority = 'HIGH' THEN 'HIGH'
                            WHEN EXCLUDED.priority = 'HIGH' THEN 'HIGH'
                            WHEN oc_intake.intelligence_items.priority = 'MEDIUM' THEN 'MEDIUM'
                            ELSE EXCLUDED.priority
                        END,
                        canonical_destinations = EXCLUDED.canonical_destinations,
                        follow_up_tasks = EXCLUDED.follow_up_tasks,
                        source_urls = EXCLUDED.source_urls,
                        dois = EXCLUDED.dois,
                        last_seen_at = NOW(),
                        updated_at = NOW()
                    RETURNING id, knowledge_fingerprint, lifecycle, knowledge_delta,
                              first_seen_at, last_seen_at, observation_count
                    """,
                    (
                        fingerprint,
                        str(item["domain"]),
                        str(item["title"]),
                        str(item.get("normalized_title") or ""),
                        str(item.get("detail") or ""),
                        str(item.get("priority") or "MEDIUM"),
                        Jsonb(list(item.get("canonical_destinations", []))),
                        Jsonb(list(item.get("follow_up_tasks", []))),
                        Jsonb(list(item.get("source_urls", []))),
                        Jsonb(list(item.get("dois", []))),
                    ),
                )
                canonical = cur.fetchone()
                if canonical is None:
                    raise RuntimeError("Intelligence item upsert returned no row")

                snapshot = {
                    "domain": item.get("domain"),
                    "title": item.get("title"),
                    "priority": item.get("priority"),
                    "detail": item.get("detail"),
                    "canonical_destinations": item.get("canonical_destinations", []),
                    "follow_up_tasks": item.get("follow_up_tasks", []),
                    "verification_required": True,
                    "canonical_graph_mutated": False,
                    "external_contacted": False,
                }
                cur.execute(
                    """
                    INSERT INTO oc_intake.intelligence_observations
                        (intelligence_item_id, source_id, observation_fingerprint, sender,
                         message_id, observed_title, observed_detail, observed_priority,
                         source_urls, dois, parser_version, raw_snapshot)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (observation_fingerprint) DO NOTHING
                    RETURNING id
                    """,
                    (
                        canonical["id"],
                        source_id,
                        str(item["intelligence_id"]),
                        sender,
                        message_id,
                        str(item["title"]),
                        str(item.get("detail") or ""),
                        str(item.get("priority") or "MEDIUM"),
                        Jsonb(list(item.get("source_urls", []))),
                        Jsonb(list(item.get("dois", []))),
                        str(item.get("parser_version") or "unknown"),
                        Jsonb(snapshot),
                    ),
                )
                observation = cur.fetchone()
                is_new_observation = observation is not None
                if is_new_observation:
                    cur.execute(
                        """
                        UPDATE oc_intake.intelligence_items
                        SET observation_count = observation_count + 1,
                            last_seen_at = NOW(), updated_at = NOW()
                        WHERE id = %s
                        RETURNING observation_count, last_seen_at
                        """,
                        (canonical["id"],),
                    )
                    counts = cur.fetchone()
                    cur.execute(
                        """
                        INSERT INTO oc_intake.intelligence_events
                            (intelligence_item_id, event_type, resulting_state, reason, origin)
                        VALUES (%s, 'OBSERVED', %s, %s, 'AUTOMATED')
                        """,
                        (
                            canonical["id"],
                            Jsonb({
                                "lifecycle": canonical["lifecycle"],
                                "knowledge_delta": canonical["knowledge_delta"],
                                "source_id": source_id,
                            }),
                            "External intelligence observation preserved; verification and comparison remain pending.",
                        ),
                    )
                else:
                    counts = {"observation_count": canonical["observation_count"], "last_seen_at": canonical["last_seen_at"]}

                recorded.append(
                    {
                        "id": canonical["id"],
                        "knowledge_fingerprint": canonical["knowledge_fingerprint"],
                        "lifecycle": canonical["lifecycle"],
                        "knowledge_delta": canonical["knowledge_delta"],
                        "observation_count": counts["observation_count"],
                        "last_seen_at": counts["last_seen_at"],
                        "new_observation": is_new_observation,
                        "canonical_graph_mutated": False,
                        "external_contacted": False,
                    }
                )
    return recorded


def list_intelligence_items(limit: int = 100) -> list[dict[str, Any]]:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, knowledge_fingerprint, domain, title, priority, lifecycle,
                       knowledge_delta, verification_required, canonical_destinations,
                       follow_up_tasks, first_seen_at, last_seen_at, observation_count,
                       canonical_promotion_prohibited, external_contact_prohibited
                FROM oc_intake.intelligence_items
                ORDER BY last_seen_at DESC, id DESC
                LIMIT %s
                """,
                (limit,),
            )
            return list(cur.fetchall())


def get_intelligence_item(item_id: int) -> dict[str, Any] | None:
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_intake.intelligence_items WHERE id=%s", (item_id,))
            item = cur.fetchone()
            if not item:
                return None
            cur.execute(
                "SELECT * FROM oc_intake.intelligence_observations WHERE intelligence_item_id=%s ORDER BY observed_at, id",
                (item_id,),
            )
            item["observations"] = list(cur.fetchall())
            cur.execute(
                "SELECT * FROM oc_intake.intelligence_events WHERE intelligence_item_id=%s ORDER BY occurred_at, id",
                (item_id,),
            )
            item["events"] = list(cur.fetchall())
            return item
