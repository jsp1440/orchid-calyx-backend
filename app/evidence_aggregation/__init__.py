"""BUILD-086B provenance-preserving evidence aggregation."""

from .models import AggregateType, CandidateInput, ConsensusStatus, EvidenceRelationship
from .repository import MemoryAggregateRepository
from .service import EvidenceAggregationService

__all__ = ["AggregateType", "CandidateInput", "ConsensusStatus", "EvidenceAggregationService", "EvidenceRelationship", "MemoryAggregateRepository"]
