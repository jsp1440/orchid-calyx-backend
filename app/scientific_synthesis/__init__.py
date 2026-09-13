"""Evidence-grounded scientific synthesis contracts and validation."""

from .governance import GovernanceDecision, GovernanceOutcome, check_manifest_governance
from .run_manifest import MANIFEST_VERSION, build_run_evidence_manifest
from .service import ScientificSynthesisService

__all__ = [
    "MANIFEST_VERSION",
    "GovernanceDecision",
    "GovernanceOutcome",
    "ScientificSynthesisService",
    "build_run_evidence_manifest",
    "check_manifest_governance",
]
