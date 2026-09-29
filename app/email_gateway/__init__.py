"""Provider-neutral inbound email boundary for Orchid Continuum.

Inbound messages are untrusted transport data.  This package normalizes routing
metadata without granting message content any execution or scientific authority.
"""

from .envelope import InboundAttachmentMetadata, InboundEmailEnvelope
from .routing import EmailRoute, EmailRoutingDecision, route_inbound_email

__all__ = [
    "EmailRoute",
    "EmailRoutingDecision",
    "InboundAttachmentMetadata",
    "InboundEmailEnvelope",
    "route_inbound_email",
]
