"""Evidence-grounded scientific synthesis contracts and validation."""

from .blueprint import (
    BLUEPRINT_VERSION,
    MAX_DEPENDENCY_DEPTH,
    MAX_TASK_COUNT,
    BlueprintValidationError,
    ResearchBlueprint,
    decompose_governed_action,
    enqueue_blueprint,
    validate_blueprint,
)
from .governance import GovernanceDecision, GovernanceOutcome, check_manifest_governance
from .run_manifest import MANIFEST_VERSION, build_run_evidence_manifest
from .service import ScientificSynthesisService

__all__ = [
    "BLUEPRINT_VERSION",
    "MANIFEST_VERSION",
    "MAX_DEPENDENCY_DEPTH",
    "MAX_TASK_COUNT",
    "BlueprintValidationError",
    "GovernanceDecision",
    "GovernanceOutcome",
    "ResearchBlueprint",
    "ScientificSynthesisService",
    "build_run_evidence_manifest",
    "check_manifest_governance",
    "decompose_governed_action",
    "enqueue_blueprint",
    "validate_blueprint",
]
