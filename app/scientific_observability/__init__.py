"""SCI-OBS-001 — Scientific Observability Foundation.

Append-only, vendor-neutral observability for the Orchid Continuum scientific
pipeline. Reuses canonical kernel identity, data-governance disclosure,
readiness metric shape, and the Verification Workbench review boundary.
Observation events carry no publication or mutation authority.
"""

from .agent_context import ContextValidationError, build_governed_agent_context
from .models import (
    ObservationEventType,
    ObservationValidationError,
    PipelineStage,
    SafeStatus,
    SafeStatusState,
    ScientificObservationEvent,
)
from .ranking import (
    ClassifiedFactor,
    MeasurementClass,
    OpportunityInput,
    RankingFactor,
    RankingValidationError,
    rank_opportunities,
    score_opportunity,
)
from .service import ObservabilityService, RecordResult
from .store import ObservationStore, get_default_store
from .workflow import (
    WorkflowActorType,
    WorkflowReconstructor,
    WorkflowStage,
    WorkflowState,
    WorkflowType,
    WorkflowValidationError,
    legal_next_states,
    parse_workflow_metadata,
    workflow_metadata,
)

__all__ = [
    "ClassifiedFactor",
    "ContextValidationError",
    "MeasurementClass",
    "ObservabilityService",
    "ObservationEventType",
    "ObservationStore",
    "ObservationValidationError",
    "OpportunityInput",
    "PipelineStage",
    "RankingFactor",
    "RankingValidationError",
    "RecordResult",
    "SafeStatus",
    "SafeStatusState",
    "ScientificObservationEvent",
    "WorkflowActorType",
    "WorkflowReconstructor",
    "WorkflowStage",
    "WorkflowState",
    "WorkflowType",
    "WorkflowValidationError",
    "build_governed_agent_context",
    "get_default_store",
    "legal_next_states",
    "parse_workflow_metadata",
    "rank_opportunities",
    "score_opportunity",
    "workflow_metadata",
]
