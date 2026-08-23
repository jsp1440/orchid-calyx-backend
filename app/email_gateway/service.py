"""Application service that separates scientific intelligence from operations mail."""

from __future__ import annotations

from typing import Any

from app.intake.email_service import ingest_external_intelligence_email
from .envelope import InboundEmailEnvelope
from .repository import ensure_operational_ticket, record_inbound_message
from .routing import EmailRoute, route_inbound_email


def process_inbound_email(envelope: InboundEmailEnvelope) -> dict[str, Any]:
    """Route and persist one provider-verified inbound message.

    Provider adapters are responsible for authenticating their webhook or OAuth
    transport before calling this service.  Message content itself is never an
    authorization source.
    """

    decision = route_inbound_email(envelope)

    if decision.route is EmailRoute.RESEARCH:
        intelligence = ingest_external_intelligence_email(
            subject=envelope.subject,
            body=envelope.body_text,
            sender=envelope.sender,
            message_id=envelope.internet_message_id or envelope.provider_message_id,
            received_at=envelope.received_at,
            imported_by=f"{envelope.provider.strip().lower()}-email-gateway",
        )
        message = record_inbound_message(
            envelope,
            decision,
            intake_source_id=int(intelligence["id"]),
        )
        return {
            "route": decision.route.value,
            "reason": decision.reason,
            "message": message,
            "intelligence": intelligence,
            "ticket": None,
            "trusted_instruction": False,
            "mailbox_mutated": False,
            "canonical_graph_mutated": False,
            "external_contacted": False,
            "publication_performed": False,
        }

    message = record_inbound_message(envelope, decision)
    ticket = ensure_operational_ticket(int(message["id"]), decision.route)
    return {
        "route": decision.route.value,
        "reason": decision.reason,
        "message": message,
        "intelligence": None,
        "ticket": ticket,
        "trusted_instruction": False,
        "mailbox_mutated": False,
        "canonical_graph_mutated": False,
        "external_contacted": False,
        "publication_performed": False,
    }
