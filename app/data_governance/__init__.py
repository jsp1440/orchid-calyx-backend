"""Policy primitives for governed partner and sensitive scientific data.

This package is intentionally provider- and storage-agnostic.  It defines the
fail-closed policy contract that database, graph, search, Calyx, and export
surfaces must enforce before restricted partner data can be accepted.
"""

from .access import access_context_from_principal
from .disclosure import DataDisclosureDenied, apply_disclosure
from .model_gate import (
    ModelProcessingAuthorization,
    ModelProcessingDenied,
    authorize_model_processing,
)
from .models import (
    DataAccessContext,
    DataPolicy,
    DataPolicyDecision,
    DataSensitivity,
    DisclosureMode,
)
from .output_guard import (
    GuardedText,
    ProtectedValue,
    ProtectedValueKind,
    guard_generated_text,
)
from .policy import DataPolicyEngine

__all__ = [
    "DataAccessContext",
    "DataDisclosureDenied",
    "DataPolicy",
    "DataPolicyDecision",
    "DataPolicyEngine",
    "DataSensitivity",
    "DisclosureMode",
    "GuardedText",
    "ModelProcessingAuthorization",
    "ModelProcessingDenied",
    "ProtectedValue",
    "ProtectedValueKind",
    "access_context_from_principal",
    "apply_disclosure",
    "authorize_model_processing",
    "guard_generated_text",
]
