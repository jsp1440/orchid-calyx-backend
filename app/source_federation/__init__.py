"""Deterministic source-federation inventory and queue-bridge helpers."""

from .inventory import (
    AccessState,
    CandidateDisposition,
    FederationCandidate,
    RightsState,
    build_default_candidate_inventory,
    deduplicate_candidates,
)
from .queue_bridge import (
    BridgeSuppression,
    SourceChildTask,
    SourceQueueBridgeResult,
    bridge_source_candidates,
    source_task_key,
)

__all__ = [
    "AccessState",
    "BridgeSuppression",
    "CandidateDisposition",
    "FederationCandidate",
    "RightsState",
    "SourceChildTask",
    "SourceQueueBridgeResult",
    "bridge_source_candidates",
    "build_default_candidate_inventory",
    "deduplicate_candidates",
    "source_task_key",
]
