"""Evidence-bound scientific inference services.

This package consumes canonical evidence aggregates and emits non-persistent,
review-required inference envelopes. It does not own evidence or publication state.
"""

from .models import InferenceDomain, InferenceState, ScientificInferenceEnvelope
from .service import ScientificInferenceService

__all__ = [
    "InferenceDomain",
    "InferenceState",
    "ScientificInferenceEnvelope",
    "ScientificInferenceService",
]
