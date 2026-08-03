from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

InquiryStage = Literal[
    "observe",
    "question",
    "investigate",
    "analyze",
    "interpret",
    "communicate",
    "contribute",
]
SessionStatus = Literal[
    "created",
    "observing",
    "questioning",
    "investigating",
    "analyzing",
    "interpreting",
    "communicating",
    "submitted",
    "under_review",
    "changes_requested",
    "approved_for_learning",
    "archived",
]


class UniversityCapability(BaseModel):
    enabled: bool
    session_writes_enabled: bool
    persistence: Literal["process_local_memory"] = "process_local_memory"
    publication_enabled: Literal[False] = False
    candidate_knowledge_writes_enabled: Literal[False] = False
    calyx_model_calls_enabled: Literal[False] = False


class CatalogItem(BaseModel):
    id: str
    title: str
    summary: str
    status: str


class CatalogResponse(BaseModel):
    chapter: CatalogItem
    laboratory: CatalogItem
    capability: UniversityCapability


class SessionCreate(BaseModel):
    laboratory_id: str = Field(pattern=r"^OCU-LAB-")
    chapter_id: str = Field(pattern=r"^BITB-CHAPTER-")


class InvestigationEventCreate(BaseModel):
    event_type: Literal[
        "observation_added",
        "question_set",
        "hypothesis_added",
        "evidence_examined",
        "analysis_recorded",
        "interpretation_recorded",
        "conclusion_drafted",
        "uncertainty_recorded",
        "stage_advanced",
    ]
    stage: InquiryStage
    payload: dict[str, Any] = Field(default_factory=dict)


class SessionEvent(BaseModel):
    event_id: str
    event_type: str
    stage: InquiryStage
    payload: dict[str, Any]
    actor: str
    created_at: datetime


class LabSession(BaseModel):
    session_id: str
    laboratory_id: str
    chapter_id: str
    actor: str
    status: SessionStatus
    current_stage: InquiryStage
    created_at: datetime
    updated_at: datetime
    revision: int = 1
    events: list[SessionEvent] = Field(default_factory=list)
    publication_allowed: Literal[False] = False
    automatic_candidate_knowledge: Literal[False] = False
    human_review_required: Literal[True] = True
