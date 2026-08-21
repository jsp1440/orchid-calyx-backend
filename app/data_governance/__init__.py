"""Policy primitives for governed partner and sensitive scientific data.

This package is intentionally provider- and storage-agnostic.  It defines the
fail-closed policy contract that database, graph, search, Calyx, and export
surfaces must enforce before restricted partner data can be accepted.
"""

from .access import access_context_from_principal
from .disclosure import DataDisclosureDenied, apply_disclosure
from .models import (
    DataAccessContext,
    DataPolicy,
    DataPolicyDecision,
    DataSensitivity,
    DisclosureMode,
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
    "access_context_from_principal",
    "apply_disclosure",
]
