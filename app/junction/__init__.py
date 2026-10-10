"""J1 — Junction router: production integration of oc-junction-profile-v1.

Module-to-module junction communication over the existing scientific
observability plane (``app.scientific_observability``). A junction signal IS a
``sci-obs-event-v1`` envelope carrying an ``extensions.junction`` block; the
append-only observation store remains the only event store, and delivery state
(cursors, idempotency, retries, dead letters, audit) is one small durable
SQLite file.

Doctrine: junctions propose; the engine disposes; the lattice remembers.
Delivery authorizes nothing: no lease, no assignment, no execution, no
publication, no Knowledge Graph or taxonomy mutation.

Contract: Orchid-Continuum-Brain ``contracts/oc_junction_profile_v1.json``
(J0, Brain PR #221, branch ``kimi/junction-profile-v1``).
"""

from .manifest import load_manifest, validate_manifest
from .profile import (
    CONSEQUENCE_CLASSES,
    HEALTH_STATES,
    HEARTBEAT_EVENT,
    JUNCTION_ADDED_EVENT_TYPES,
    KNOWN_EVENT_TYPES,
    MAX_RETRY_ATTEMPTS,
    PROFILE_ID,
    JunctionValidationError,
    dedupe_key,
)
from .router import JunctionRouter
from .signals import build_signal, validate_signal
from .state import JunctionStateStore

__all__ = [
    "CONSEQUENCE_CLASSES",
    "HEALTH_STATES",
    "HEARTBEAT_EVENT",
    "JUNCTION_ADDED_EVENT_TYPES",
    "JunctionRouter",
    "JunctionStateStore",
    "JunctionValidationError",
    "KNOWN_EVENT_TYPES",
    "MAX_RETRY_ATTEMPTS",
    "PROFILE_ID",
    "build_signal",
    "dedupe_key",
    "load_manifest",
    "validate_manifest",
    "validate_signal",
]
