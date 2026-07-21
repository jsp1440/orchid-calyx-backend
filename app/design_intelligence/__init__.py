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
from .population import (
    ARCHIVE_DRIVE_ID,
    ARCHIVE_SHA256,
    ARCHIVE_VERSION,
    REUSE_LICENSE,
    RIGHTS_STATE,
    UNKNOWN_AUTHOR,
    CorpusFile,
    DesignCorpusPopulationService,
    ProvenanceBinding,
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
    "ARCHIVE_DRIVE_ID",
    "ARCHIVE_SHA256",
    "ARCHIVE_VERSION",
    "REUSE_LICENSE",
    "RIGHTS_STATE",
    "UNKNOWN_AUTHOR",
    "CorpusFile",
    "DesignCorpusPopulationService",
    "ProvenanceBinding",
]
