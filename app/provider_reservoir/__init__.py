"""Capability-based routing and the provider-request reservoir.

Two defects this package exists to remove, both observed live on issue #1502:

1. **Default-to-provider routing.** The swarm controller recognised exactly one
   provider-free task name, so every other task — including one whose own
   acceptance criteria said "provider-free fixture must run without external AI
   credentials" — was routed to a paid provider lane.

2. **Escalation on complexity rather than capability.** The model router promoted
   #1502 to the most expensive tier because its body contained the word
   "architecture". The receipt reads ``reason=default=cheap;deep-complexity-signal``.
   A task being hard is not evidence that it needs a provider; needing a
   capability no deterministic executor has is.

The rule this package enforces is that **provider requirement is established by
capability, never by difficulty**, and that a denied provider request is
preserved with its reasoning rather than collapsing into "blocked".
"""

from .capabilities import (
    CAPABILITIES,
    Capability,
    CapabilityUnknown,
    classify_capabilities,
    is_provider_capability,
)
from .intent import (
    INTENT_SCHEMA,
    ProviderIntentRecord,
    redact,
)
from .reservoir import (
    ProviderRequestReservoir,
    ReservoirState,
)
from .routing import (
    TaskRouting,
    route_task,
)

__all__ = [
    "CAPABILITIES",
    "INTENT_SCHEMA",
    "Capability",
    "CapabilityUnknown",
    "ProviderIntentRecord",
    "ProviderRequestReservoir",
    "ReservoirState",
    "TaskRouting",
    "classify_capabilities",
    "is_provider_capability",
    "redact",
    "route_task",
]
