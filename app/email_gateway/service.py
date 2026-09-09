"""Application service that separates scientific intelligence from operations mail."""

from __future__ import annotations

from typing import Any

from app.intake.email_service import ingest_external_intelligence_email

from .envelope import InboundEmailEnvelope
from .repository import (
    ensure_operational_ticket,
    link_intake_source,
    record_inbound_message,
)
from .routing import EmailRoute, route_inbound_email


def _base_receipt(route: str, reason: str) -> dict[str, Any]:
    return {
        "route": route,
        "reason": reason,
        "trusted_instruction": False,
        "mailbox_mutated": False,
        "canonical_graph_mutated": False,
        "external_contacted": False,
        "publication_performed": False,
    }


def process_inbound_email(envelope: InboundEmailEnvelope) -> dict[str, Any]:
    """Route and persist one provider-verified inbound message.

    Provider adapters are responsible for authenticating their webhook or OAuth
    transport before calling this service. Message content itself is never an
    authorization source. The transport ledger is consulted before research
    assimilation so provider replays cannot create new scientific intake work.
    """

    decision = route_inbound_email(envelope)
    message = record_inbound_message(envelope, decision)

    if decision.route is EmailRoute.RESEARCH:
        existing_source_id = message.get("intake_source_id")
        if message.get("duplicate") and existing_source_id is not None:
            return {
                **_base_receipt(decision.route.value, decision.reason),
                "message": message,
                "intelligence": {
                    "id": int(existing_source_id),
                    "duplicate": True,
                    "replayed_from_transport_ledger": True,
                },
                "ticket": None,
            }

        intelligence = ingest_external_intelligence_email(
            subject=envelope.subject,
            body=envelope.body_text,
            sender=envelope.sender,
            message_id=envelope.internet_message_id or envelope.provider_message_id,
            received_at=envelope.received_at,
            imported_by=f"{envelope.provider.strip().lower()}-email-gateway",
        )
        message = link_intake_source(int(message["id"]), int(intelligence["id"]))
        message["duplicate"] = bool(message.get("duplicate", False))
        return {
            **_base_receipt(decision.route.value, decision.reason),
            "message": message,
            "intelligence": intelligence,
            "ticket": None,
        }

    ticket = ensure_operational_ticket(int(message["id"]), decision.route)
    return {
        **_base_receipt(decision.route.value, decision.reason),
        "message": message,
        "intelligence": None,
        "ticket": ticket,
    }
