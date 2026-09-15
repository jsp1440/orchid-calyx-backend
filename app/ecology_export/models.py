from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class HabitatType(str, Enum):
    TERRESTRIAL = "TERRESTRIAL"
    EPIPHYTIC = "EPIPHYTIC"
    LITHOPHYTIC = "LITHOPHYTIC"
    AQUATIC = "AQUATIC"
    UNKNOWN = "UNKNOWN"


class EcologyExportFormat(str, Enum):
    JSON = "JSON"
    CSV = "CSV"


class EcologyRecord(BaseModel):
    taxon_name: str
    common_name: str | None = None
    habitat_type: HabitatType
    region_verbatim: str | None = None
    elevation_m: float | None = None
    notes: str | None = None
    source_reference: str | None = None
    exported_at: datetime


class EcologyExportRequest(BaseModel):
    format: EcologyExportFormat = EcologyExportFormat.JSON
    habitat_type: HabitatType | None = None
    region_filter: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class EcologyExportResponse(BaseModel):
    format: EcologyExportFormat
    records: list[EcologyRecord]
    total: int
    offset: int
    limit: int
    exported_at: datetime
