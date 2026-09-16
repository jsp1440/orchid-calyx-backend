"""ARK continuity state API routes — Journey 15: Species Archive/Recovery Continuity.

Owner-gated read-only endpoints exposing ARK run status and evidence.
In-memory stub for R1 MVP; full DB integration is a follow-up.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from app.security import verify_owner_or_api_key

from .models import (
    ArkEvidenceResponse,
    ArkRunOutcome,
    ArkRunSummary,
    ArkStatusResponse,
    ContinuityState,
)

router = APIRouter(
    prefix="/api/ark",
    tags=["ark"],
    dependencies=[Depends(verify_owner_or_api_key)],
)

_STUB_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
_STUB_TS = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_stub_runs: list[ArkRunSummary] = [
    ArkRunSummary(
        run_id=_STUB_RUN_ID,
        started_at=_STUB_TS,
        completed_at=_STUB_TS,
        outcome=ArkRunOutcome.SUCCESS,
        species_verified=42,
        species_degraded=0,
        notes="Stub run — DB integration pending.",
    )
]


@router.get("/status", response_model=ArkStatusResponse)
def get_ark_status() -> ArkStatusResponse:
    """Return overall ARK continuity state and last-verified timestamp."""
    return ArkStatusResponse(
        overall_state=ContinuityState.VERIFIED,
        species_count=42,
        last_verified_at=_STUB_TS,
        last_run_id=_STUB_RUN_ID,
    )


@router.get("/runs", response_model=list[ArkRunSummary])
def list_ark_runs() -> list[ArkRunSummary]:
    """List ARK continuity run summaries, newest first."""
    return list(reversed(_stub_runs))


@router.get("/evidence/{run_id}", response_model=ArkEvidenceResponse)
def get_ark_evidence(
    run_id: Annotated[uuid.UUID, Path(description="ARK run UUID.")],
) -> ArkEvidenceResponse:
    """Return evidence items collected during a specific ARK run."""
    if run_id != _STUB_RUN_ID:
        raise HTTPException(status_code=404, detail="ARK run not found.")
    return ArkEvidenceResponse(
        run_id=run_id,
        outcome=ArkRunOutcome.SUCCESS,
        evidence_items=["42 species verified against backup store."],
        collected_at=_STUB_TS,
    )
