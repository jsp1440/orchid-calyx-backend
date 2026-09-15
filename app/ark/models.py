"""ARK continuity state models — Journey 15: Species Archive/Recovery Continuity."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class ContinuityState(str, Enum):
    DISCOVERED = "DISCOVERED"
    PROTECTED = "PROTECTED"
    VERIFIED = "VERIFIED"
    RESTORE_TESTED = "RESTORE_TESTED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"


class ArkRunOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ArkRunSummary(BaseModel):
    run_id: UUID
    started_at: datetime
    completed_at: datetime | None = None
    outcome: ArkRunOutcome
    species_verified: int = Field(ge=0)
    species_degraded: int = Field(ge=0)
    notes: str | None = None


class ArkStatusResponse(BaseModel):
    overall_state: ContinuityState
    species_count: int = Field(ge=0)
    last_verified_at: datetime | None = None
    last_run_id: UUID | None = None


class ArkEvidenceResponse(BaseModel):
    run_id: UUID
    outcome: ArkRunOutcome
    evidence_items: list[str]
    collected_at: datetime
