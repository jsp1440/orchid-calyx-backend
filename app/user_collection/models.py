from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class CareStatus(str, Enum):
    THRIVING = "THRIVING"
    HEALTHY = "HEALTHY"
    DECLINING = "DECLINING"
    DORMANT = "DORMANT"
    UNKNOWN = "UNKNOWN"


class AcquisitionSource(str, Enum):
    PURCHASED = "PURCHASED"
    TRADED = "TRADED"
    PROPAGATED = "PROPAGATED"
    GIFTED = "GIFTED"
    RESCUED = "RESCUED"
    UNKNOWN = "UNKNOWN"


class CollectionItem(BaseModel):
    id: UUID
    user_auth_subject: str
    taxon_name_verbatim: str
    common_name: str | None = None
    care_status: CareStatus = CareStatus.UNKNOWN
    acquisition_source: AcquisitionSource = AcquisitionSource.UNKNOWN
    acquired_at: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    last_bloom_at: date | None = None
    created_at: datetime
    updated_at: datetime


class CollectionItemCreate(BaseModel):
    taxon_name_verbatim: str
    common_name: str | None = None
    care_status: CareStatus = CareStatus.UNKNOWN
    acquisition_source: AcquisitionSource = AcquisitionSource.UNKNOWN
    acquired_at: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    last_bloom_at: date | None = None


class CollectionItemPatch(BaseModel):
    taxon_name_verbatim: str | None = None
    common_name: str | None = None
    care_status: CareStatus | None = None
    acquisition_source: AcquisitionSource | None = None
    acquired_at: date | None = None
    notes: str | None = Field(default=None, max_length=2000)
    last_bloom_at: date | None = None


class CollectionListResponse(BaseModel):
    items: list[CollectionItem]
    total: int
