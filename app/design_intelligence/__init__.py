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

__all__ = [
    "DesignDomain",
    "DesignDocument",
    "DesignDocumentInput",
    "DesignIntelligenceService",
    "DesignKnowledgeType",
    "DesignProvenance",
    "DesignReviewDecision",
    "DesignSearchQuery",
    "MemoryDesignCorpusRepository",
    "PostgresDesignCorpusRepository",
    "PublicationStatus",
    "ReviewState",
]
