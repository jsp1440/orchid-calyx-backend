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


class EmailIntakeRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1)
    sender: str = Field(min_length=3, max_length=320)
    message_id: Optional[str] = Field(default=None, max_length=500)
    received_at: Optional[str] = Field(default=None, max_length=100)
    imported_by: Optional[str] = Field(default=None, max_length=200)


class ReviewDecision(BaseModel):
    notes: Optional[str] = None


class DocumentReview(BaseModel):
    action: str
    classification: Optional[str] = None
    note: Optional[str] = None
    actor: Optional[str] = Field(default=None, max_length=200)


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


class HumanObservationRequest(BaseModel):
    """Ingest a human observation of a biological relationship or event.
    
    Human observations provide local, direct evidence of interactions, behaviors,
    and relationships not captured in aggregated occurrence datasets or literature.
    This evidence class supports gap-filling in reasoning about species behaviors
    and relationships.
    """
    subject: str = Field(
        min_length=1,
        max_length=500,
        description="The organism or entity being observed (e.g., species name, individual, population)"
    )
    predicate: str = Field(
        min_length=1,
        max_length=200,
        description="The relationship or event (e.g., 'pollinated_by', 'feeding_on', 'nesting_in')"
    )
    object: str = Field(
        min_length=1,
        max_length=500,
        description="The target of the observation (e.g., pollinator species, food source)"
    )
    observation_date: Optional[str] = Field(
        default=None,
        max_length=100,
        description="Date or date range of the observation (e.g., '2024-06-15' or 'June 2024')"
    )
    location: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Geographic location or habitat where observation was made (no precise coordinates)"
    )
    observer_name: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Name of the person who made the observation"
    )
    observation_notes: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="Detailed notes about the observation, context, and any notable details"
    )
    confidence: Optional[str] = Field(
        default="unspecified",
        max_length=50,
        description="Confidence level in the observation (e.g., 'certain', 'probable', 'possible')"
    )
    imported_by: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Source or system that imported this observation"
    )


class ExtractionResult(BaseModel):
    entities: list[IntakeEntity]
    relationships: list[IntakeRelationship]
    tasks: list[IntakeTask]
    parser_version: str
