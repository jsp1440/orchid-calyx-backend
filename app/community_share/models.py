"""Community share models for Journey 11: Observation/Research Artifact sharing with audience-scoped visibility."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AudienceScope(str, Enum):
    PRIVATE = "PRIVATE"
    MEMBERS_ONLY = "MEMBERS_ONLY"
    PUBLIC = "PUBLIC"


class ArtifactKind(str, Enum):
    OBSERVATION = "OBSERVATION"
    RESEARCH_ARTIFACT = "RESEARCH_ARTIFACT"
    FIELD_OBSERVATION = "FIELD_OBSERVATION"
    LITERATURE_INTEL = "LITERATURE_INTEL"


class ShareRequest(BaseModel):
    artifact_id: str
    artifact_kind: ArtifactKind
    audience: AudienceScope
    sharer_auth_subject: str
    expires_at: Optional[datetime] = None
    note: Optional[str] = None


class ShareRecord(BaseModel):
    id: str
    artifact_id: str
    artifact_kind: ArtifactKind
    audience: AudienceScope
    sharer_auth_subject: str
    share_token: str
    created_at: datetime
    expires_at: Optional[datetime] = None
    is_active: bool = True


class ShareLookupResponse(BaseModel):
    share_record: Optional[ShareRecord] = None
    artifact_preview: dict = Field(default_factory=dict)


class ShareListResponse(BaseModel):
    items: list[ShareRecord]
    total: int
