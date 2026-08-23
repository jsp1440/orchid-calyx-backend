"""Deterministic, fail-closed routing for inbound Orchid Continuum email."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .envelope import InboundEmailEnvelope


class EmailRoute(str, Enum):
    RESEARCH = "research"
    SUPPORT = "support"
    BUG = "bug"
    ADMIN = "admin"
    REVIEW = "review"


RECIPIENT_ROUTE_MAP: dict[str, EmailRoute] = {
    "research": EmailRoute.RESEARCH,
    "intake": EmailRoute.RESEARCH,
    "support": EmailRoute.SUPPORT,
    "help": EmailRoute.SUPPORT,
    "bugs": EmailRoute.BUG,
    "bug": EmailRoute.BUG,
    "admin": EmailRoute.ADMIN,
}

TWIN_SENDER = "twin@twin-mail.com"
TWIN_SUBJECT_PREFIX = "orchid continuum daily briefing"


@dataclass(frozen=True)
class EmailRoutingDecision:
    route: EmailRoute
    reason: str
    matched_recipient: str | None = None
    trusted_instruction: bool = False
    canonical_graph_mutation_allowed: bool = False
    external_contact_allowed: bool = False
    publication_allowed: bool = False


def _local_part(address: str) -> str:
    local = address.strip().lower().split("@", 1)[0]
    return local.split("+", 1)[0]


def route_inbound_email(envelope: InboundEmailEnvelope) -> EmailRoutingDecision:
    """Route by controlled envelope metadata, never by executable message commands.

    Recipient aliases are authoritative routing hints.  If a message targets
    multiple trust domains, routing fails closed to review.  The exact historical
    Twin sender/subject pair remains a safe compatibility path for direct
    collection even before `research@` is provisioned.
    """

    matches: list[tuple[str, EmailRoute]] = []
    for recipient in envelope.recipients:
        route = RECIPIENT_ROUTE_MAP.get(_local_part(recipient))
        if route:
            matches.append((recipient, route))

    distinct_routes = {route for _, route in matches}
    if len(distinct_routes) == 1:
        matched_recipient, route = matches[0]
        return EmailRoutingDecision(
            route=route,
            reason="recognized_recipient_alias",
            matched_recipient=matched_recipient,
        )

    if len(distinct_routes) > 1:
        return EmailRoutingDecision(
            route=EmailRoute.REVIEW,
            reason="multiple_trust_domain_recipients",
        )

    sender = envelope.sender.strip().lower()
    subject = envelope.subject.strip().lower()
    if sender == TWIN_SENDER and subject.startswith(TWIN_SUBJECT_PREFIX):
        return EmailRoutingDecision(
            route=EmailRoute.RESEARCH,
            reason="validated_twin_compatibility_rule",
        )

    return EmailRoutingDecision(
        route=EmailRoute.REVIEW,
        reason="unrecognized_recipient_or_source",
    )
