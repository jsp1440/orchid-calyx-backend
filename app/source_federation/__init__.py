"""Deterministic source-federation inventory helpers."""

from .inventory import (
    AccessState,
    CandidateDisposition,
    FederationCandidate,
    RightsState,
    build_default_candidate_inventory,
    deduplicate_candidates,
)

__all__ = [
    "AccessState",
    "CandidateDisposition",
    "FederationCandidate",
    "RightsState",
    "build_default_candidate_inventory",
    "deduplicate_candidates",
]
