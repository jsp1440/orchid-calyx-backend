"""BUILD-089A design intelligence corpus."""

from .models import (
    DesignDomain,
    DesignDocument,
    DesignDocumentInput,
    DesignKnowledgeType,
    DesignProvenance,
    DesignReviewDecision,
    PublicationStatus,
    ReviewState,
)
from .repository import MemoryDesignCorpusRepository
from .postgres_repository import PostgresDesignCorpusRepository
from .service import DesignIntelligenceService, DesignSearchQuery
from .acquisition import AcquisitionMetadata, DesignDocumentAcquirer
from .knowledge import (
    DesignRelationship,
    EducationalClassification,
    RelationshipType,
    SemanticDesignDomain,
    SemanticUnit,
    SemanticUnitType,
    SourceLocation,
)
from .reasoning import (
    DesignReasoningService,
    MemoryDesignKnowledgeRepository,
    SemanticDecomposer,
)

__all__ = [
    "DesignDomain",
    "DesignDocument",
    "DesignDocumentInput",
    "DesignIntelligenceService",
    "DesignKnowledgeType",
    "DesignProvenance",
    "DesignReviewDecision",
    "DesignSearchQuery",
    "AcquisitionMetadata",
    "DesignDocumentAcquirer",
    "DesignRelationship",
    "EducationalClassification",
    "RelationshipType",
    "SemanticDesignDomain",
    "SemanticUnit",
    "SemanticUnitType",
    "SourceLocation",
    "DesignReasoningService",
    "MemoryDesignKnowledgeRepository",
    "SemanticDecomposer",
    "MemoryDesignCorpusRepository",
    "PostgresDesignCorpusRepository",
    "PublicationStatus",
    "ReviewState",
]
