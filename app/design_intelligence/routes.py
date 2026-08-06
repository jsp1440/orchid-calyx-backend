from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.persistence.state_repository import configured_database_url
from app.security import verify_owner_or_api_key

from .knowledge import SemanticDesignDomain
from .models import DesignDomain, DesignKnowledgeType
from .reasoning import DesignReasoningService, MemoryDesignKnowledgeRepository
from .repository import MemoryDesignCorpusRepository
from .service import DesignIntelligenceService, DesignSearchQuery

router = APIRouter(
    prefix="/api/design-intelligence",
    tags=["design-intelligence"],
    dependencies=[Depends(verify_owner_or_api_key)],
)
if database_url := configured_database_url():
    from .postgres_repository import PostgresDesignCorpusRepository

    REPOSITORY = PostgresDesignCorpusRepository(database_url)
else:
    REPOSITORY = MemoryDesignCorpusRepository()
SERVICE = DesignIntelligenceService(REPOSITORY)
if database_url := configured_database_url():
    from .postgres_knowledge_repository import PostgresDesignKnowledgeRepository

    KNOWLEDGE_REPOSITORY = PostgresDesignKnowledgeRepository(database_url)
else:
    KNOWLEDGE_REPOSITORY = MemoryDesignKnowledgeRepository()
REASONING_SERVICE = DesignReasoningService(KNOWLEDGE_REPOSITORY)


class DesignSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    domains: list[DesignDomain] = []
    knowledge_types: list[DesignKnowledgeType] = []
    topics: list[str] = []
    limit: int = Field(10, ge=1, le=100)
    offset: int = Field(0, ge=0, le=10_000)


class DesignReasoningSearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    domains: list[SemanticDesignDomain] = []
    classifications: list[str] = []
    citation: str | None = Field(None, max_length=500)
    limit: int = Field(10, ge=1, le=100)


@router.post("/search")
def search(payload: DesignSearchIn):
    try:
        return SERVICE.search(
            DesignSearchQuery(
                text=payload.query,
                domains=tuple(payload.domains),
                knowledge_types=tuple(payload.knowledge_types),
                topics=tuple(payload.topics),
                limit=payload.limit,
                offset=payload.offset,
            )
        )
    except ValueError as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


@router.post("/reasoning-search")
def reasoning_search(payload: DesignReasoningSearchIn):
    try:
        return REASONING_SERVICE.search(
            payload.query,
            domains=tuple(payload.domains),
            classifications=tuple(payload.classifications),
            citation=payload.citation,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


@router.get("/configuration")
def configuration():
    return {
        "domains": [item.value for item in DesignDomain],
        "knowledge_types": [item.value for item in DesignKnowledgeType],
        "classification_version": SERVICE.CLASSIFIER_VERSION,
        "semantic_classification_version": REASONING_SERVICE.CLASSIFIER_VERSION,
        "semantic_domains": [item.value for item in SemanticDesignDomain],
        "published_only": True,
        "read_only": True,
    }
