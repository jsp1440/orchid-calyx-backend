from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, HttpUrl


class SourceType(str, Enum):
    text = "text"
    url = "url"
    file = "file"
    email = "email"
    api = "api"


class IntakeStatus(str, Enum):
    new = "NEW"
    parsed = "PARSED"
    review = "REVIEW"
    approved = "APPROVED"
    published = "PUBLISHED"
    rejected = "REJECTED"


class TextIntakeRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)
    source_url: Optional[HttpUrl] = None
    imported_by: Optional[str] = Field(default=None, max_length=200)


class UrlIntakeRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    source_url: HttpUrl
    content: str = Field(min_length=1, description="Fetched content supplied by a trusted caller; server-side URL fetching is intentionally disabled in BUILD-070.")
    imported_by: Optional[str] = Field(default=None, max_length=200)


class ReviewDecision(BaseModel):
    notes: Optional[str] = None


class IntakeEntity(BaseModel):
    entity_type: str
    canonical_name: str
    normalized_name: str
    confidence: float
    exact_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntakeRelationship(BaseModel):
    subject_name: str
    predicate: str
    object_name: str
    confidence: float
    evidence_text: str


class IntakeTask(BaseModel):
    task_type: str
    title: str
    priority: str = "MEDIUM"
    rationale: Optional[str] = None


class ExtractionResult(BaseModel):
    entities: list[IntakeEntity]
    relationships: list[IntakeRelationship]
    tasks: list[IntakeTask]
    parser_version: str
