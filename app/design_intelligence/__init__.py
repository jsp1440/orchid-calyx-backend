"""BUILD-089A design intelligence corpus."""

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
from .models import (
    DesignDocument,
    DesignDocumentInput,
    DesignDomain,
    DesignKnowledgeType,
    DesignProvenance,
    DesignReviewDecision,
    PublicationStatus,
    ReviewState,
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
from .postgres_repository import PostgresDesignCorpusRepository
from .reasoning import (
    DesignReasoningService,
    MemoryDesignKnowledgeRepository,
    SemanticDecomposer,
)
from .repository import MemoryDesignCorpusRepository
from .service import DesignIntelligenceService, DesignSearchQuery

__all__ = [
    "ARCHIVE_DRIVE_ID",
    "ARCHIVE_SHA256",
    "ARCHIVE_VERSION",
    "REUSE_LICENSE",
    "RIGHTS_STATE",
    "UNKNOWN_AUTHOR",
    "AcquisitionMetadata",
    "CorpusFile",
    "DesignCorpusPopulationService",
    "DesignDocument",
    "DesignDocumentAcquirer",
    "DesignDocumentInput",
    "DesignDomain",
    "DesignIntelligenceService",
    "DesignKnowledgeType",
    "DesignProvenance",
    "DesignReasoningService",
    "DesignRelationship",
    "DesignReviewDecision",
    "DesignSearchQuery",
    "EducationalClassification",
    "MemoryDesignCorpusRepository",
    "MemoryDesignKnowledgeRepository",
    "PostgresDesignCorpusRepository",
    "ProvenanceBinding",
    "PublicationStatus",
    "RelationshipType",
    "ReviewState",
    "SemanticDecomposer",
    "SemanticDesignDomain",
    "SemanticUnit",
    "SemanticUnitType",
    "SourceLocation",
]
