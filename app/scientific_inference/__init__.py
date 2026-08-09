"""Evidence-bound scientific inference services.

This package consumes canonical evidence aggregates and emits non-persistent,
review-required inference envelopes. It does not own evidence or publication state.
"""

from .canonical_resolver import (
    CanonicalAggregateResolutionError,
    CanonicalAggregateResolver,
)
from .models import InferenceDomain, InferenceState, ScientificInferenceEnvelope
from .service import ScientificInferenceService

__all__ = [
    "CanonicalAggregateResolutionError",
    "CanonicalAggregateResolver",
    "InferenceDomain",
    "InferenceState",
    "ScientificInferenceEnvelope",
    "ScientificInferenceService",
]
