"""Pydantic models for the ARK continuity state and backup/recovery API.

Reflects the state machine defined in Brain blueprint
OC-ARK-001-autonomous-preservation-recovery-blueprint.md.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel


class ContinuityState(str, Enum):
    """State machine for each protected asset's continuity lifecycle.

    Transitions:
        DISCOVERED → PROTECTED → VERIFIED → RESTORE_TESTED
        Any state  → DEGRADED → FAILED → RECOVERING → PROTECTED
    """

    DISCOVERED = "DISCOVERED"
    PROTECTED = "PROTECTED"
    VERIFIED = "VERIFIED"
    RESTORE_TESTED = "RESTORE_TESTED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    RECOVERING = "RECOVERING"


class ArkRunOutcome(str, Enum):
    """Outcome of a single ARK backup/verification run."""

    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ArkRunSummary(BaseModel):
    """Summary of one ARK run (backup, mirror, verification cycle)."""

    run_id: str
    run_at: datetime
    outcome: ArkRunOutcome
    git_mirror_ok: bool
    pg_dump_ok: bool
    blob_ok: bool | None = None
    sha256_manifest_ok: bool
    restore_smoke_ok: bool | None = None
    notes: str | None = None


class ArkStatusResponse(BaseModel):
    """Current continuity state of the system as observed by OC-ARK."""

    continuity_state: ContinuityState
    last_run_at: datetime | None = None
    last_successful_run_at: datetime | None = None
    run_count: int
    restore_tested: bool


class ArkEvidenceResponse(BaseModel):
    """Detailed evidence for a specific ARK run, including SHA-256 manifest."""

    run_id: str
    sha256_manifest: dict[str, Any]
    restore_log: str | None = None
    run_details: ArkRunSummary
