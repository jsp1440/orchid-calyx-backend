"""Persistence for the provider-neutral inbound email ledger."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.intake.repository import database_url

from .envelope import InboundEmailEnvelope
from .routing import EmailRoute, EmailRoutingDecision


def _attachment_json(envelope: InboundEmailEnvelope) -> list[dict[str, Any]]:
    return [
        {
            "filename": item.filename,
            "content_type": item.content_type,
            "size_bytes": item.size_bytes,
            "sha256": item.sha256,
            "provider_attachment_id": item.provider_attachment_id,
        }
        for item in envelope.attachments
    ]


def record_inbound_message(
    envelope: InboundEmailEnvelope,
    decision: EmailRoutingDecision,
    *,
    intake_source_id: int | None = None,
) -> dict[str, Any]:
    """Insert idempotently by provider message ID and return the durable ledger row."""

    with (
        psycopg.connect(database_url(), row_factory=dict_row) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            INSERT INTO oc_email.inbound_messages (
                provider, provider_message_id, internet_message_id, thread_id,
                sender, reply_to, recipients, subject, body_text, received_at,
                content_sha256, route, route_reason, trust_metadata,
                attachment_metadata, intake_source_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (provider, provider_message_id) DO NOTHING
            RETURNING *
            """,
            (
                envelope.provider.strip().lower(),
                envelope.provider_message_id.strip(),
                envelope.internet_message_id,
                envelope.thread_id,
                envelope.sender.strip().lower(),
                envelope.reply_to.strip().lower() if envelope.reply_to else None,
                Jsonb(list(envelope.recipients)),
                envelope.subject,
                envelope.body_text,
                envelope.received_at,
                envelope.content_sha256(),
                decision.route.value,
                decision.reason,
                Jsonb(dict(envelope.trust_metadata)),
                Jsonb(_attachment_json(envelope)),
                intake_source_id,
            ),
        )
        inserted = cur.fetchone()
        if inserted is not None:
            inserted["duplicate"] = False
            return inserted

        cur.execute(
            """
            SELECT * FROM oc_email.inbound_messages
            WHERE provider = %s AND provider_message_id = %s
            """,
            (envelope.provider.strip().lower(), envelope.provider_message_id.strip()),
        )
        existing = cur.fetchone()
        if existing is None:
            raise RuntimeError("Duplicate inbound email could not be re-read")
        existing["duplicate"] = True
        return existing


def link_intake_source(message_id: int, source_id: int) -> dict[str, Any]:
    """Attach the governed intelligence source once without permitting relinking."""

    with (
        psycopg.connect(database_url(), row_factory=dict_row) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            UPDATE oc_email.inbound_messages
            SET intake_source_id = %s
            WHERE id = %s AND (intake_source_id IS NULL OR intake_source_id = %s)
            RETURNING *
            """,
            (source_id, message_id, source_id),
        )
        linked = cur.fetchone()
        if linked is None:
            raise RuntimeError("Inbound email is already linked to a different intake source")
        return linked


def ensure_operational_ticket(message_id: int, route: EmailRoute) -> dict[str, Any]:
    """Create one ticket per operational/review email, idempotently."""

    if route not in {EmailRoute.SUPPORT, EmailRoute.BUG, EmailRoute.ADMIN, EmailRoute.REVIEW}:
        raise ValueError("OPERATIONAL_TICKET_ROUTE_REQUIRED")

    with (
        psycopg.connect(database_url(), row_factory=dict_row) as conn,
        conn.cursor() as cur,
    ):
        cur.execute(
            """
            INSERT INTO oc_email.tickets (inbound_message_id, category)
            VALUES (%s, %s)
            ON CONFLICT (inbound_message_id) DO NOTHING
            RETURNING *
            """,
            (message_id, route.value),
        )
        inserted = cur.fetchone()
        if inserted is not None:
            inserted["duplicate"] = False
            return inserted

        cur.execute(
            "SELECT * FROM oc_email.tickets WHERE inbound_message_id = %s",
            (message_id,),
        )
        existing = cur.fetchone()
        if existing is None:
            raise RuntimeError("Duplicate email ticket could not be re-read")
        existing["duplicate"] = True
        return existing
