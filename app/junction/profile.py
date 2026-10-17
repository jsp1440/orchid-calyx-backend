"""oc-junction-profile-v1 constants and canonical helpers for the J1 router.

This module mirrors, byte-for-byte in semantics, the J0 design contract
(Orchid-Continuum-Brain ``contracts/oc_junction_profile_v1.json``) and its
stdlib reference validator (``scripts/oc_junction_validate.py``). The contract
governs; this module only makes the contract importable by the router.

Doctrine: junctions propose; the engine disposes; the lattice remembers.
A junction signal IS a ``sci-obs-event-v1`` envelope carrying an
``extensions.junction`` block. Delivery never creates a lease, an assignment,
or any execution authority.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

PROFILE_ID = "oc-junction-profile-v1"
PROFILE_SCHEMA_ID = "oc.junction-profile.v1"
MANIFEST_VERSION = "oc-junction-manifest-v1"
SUPPORTED_PROFILE_MAJOR = 1
SCI_OBS_SCHEMA_VERSION = "sci-obs-event-v1"

# Reused sci-obs vocabulary (contracts/scientific_observability_vocabulary_v1.json),
# mirrored by app/scientific_observability/models.py ObservationEventType.
SCI_OBS_EVENT_TYPES = frozenset(
    {
        "harvest.run.started",
        "harvest.run.completed",
        "harvest.run.blocked",
        "taxonomy.name.resolved",
        "taxonomy.name.conflict_detected",
        "evidence.assertion.created",
        "evidence.assertion.verified",
        "evidence.assertion.conflicted",
        "evidence.assertion.withheld",
        "artifact.created",
        "graph.write.requested",
        "graph.write.accepted",
        "graph.write.refused",
        "api.contract.produced",
        "api.contract.refused",
        "frontend.assertion.rendered",
        "frontend.assertion.withheld",
        "locality.access.denied",
        "ai.provider.used",
        "ai.provider.fallback",
        "ai.provider.blocked",
        "module.readiness.changed",
    }
)

# Junction additions declared by oc-junction-profile-v1. The event vocabulary is
# a closed, append-only enum: new types require a contract version bump.
JUNCTION_ADDED_EVENT_TYPES = frozenset(
    {
        "distribution.changed",
        "vision.image_verified",
        "pollination.link_found",
        "mycorrhiza.link_found",
        "conservation.status_changed",
        "coverage.gap_detected",
        "engine.dependency.ready",
    }
)

KNOWN_EVENT_TYPES = SCI_OBS_EVENT_TYPES | JUNCTION_ADDED_EVENT_TYPES

HEALTH_STATES = ("open", "restricted", "closed", "quarantined")
HEARTBEAT_EVENT = "module.readiness.changed"
CONSEQUENCE_CLASSES = ("observation", "action_request")

# Keys that would turn a signal into an authority claim. Never permitted; any
# junction block containing one is rejected at the port (fail-closed).
FORBIDDEN_JUNCTION_KEYS = frozenset(
    {
        "grant_execution",
        "execute_work",
        "publication_authority",
        "merge_authority",
        "deploy_authority",
    }
)

MAX_TTL_HOPS = 8
# Bounded retries, aligned with the canonical lease max_attempts default and
# the J0 delivery semantics.
MAX_RETRY_ATTEMPTS = 3
MAX_PAYLOAD_BYTES = 4096

# Subscriber-side verification floor ranking (manifest subscribes[].min_verification_state).
# A signal is delivered only when its evidence.verification_state ranks at or
# above the subscription floor. Absent state means "unknown" — never coerced
# to anything stronger.
VERIFICATION_STATE_RANK = {
    "unknown": 0,
    "unverified": 1,
    "failed": 1,
    "withheld": 1,
    "conflicted": 2,
    "review_required": 2,
    "verified": 3,
}


def canonical_json(value: Any) -> str:
    """Deterministic JSON rendering used for fingerprints and budget checks."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def dedupe_key(*, source_module: str, event_type: str, entity_scope: str, payload: Any) -> str:
    """Deterministic junction dedupe key (fingerprint identity pattern).

    Identical rule to the J0 validator and to
    ``app/scientific_observability/readiness_change.py`` /
    ``runtime/knowledge_gap_queue_bridge.py``: sha256 of the canonical JSON of
    source_module + event_type + entity_scope + payload.
    """

    material = {
        "source_module": source_module,
        "event_type": event_type,
        "entity_scope": entity_scope,
        "payload": payload,
    }
    return hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()


class JunctionValidationError(ValueError):
    """Raised when a manifest or signal violates oc-junction-profile-v1."""

    def __init__(self, failures: list[str]) -> None:
        self.failures = list(failures)
        super().__init__("; ".join(self.failures))
