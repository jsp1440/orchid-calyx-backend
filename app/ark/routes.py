"""ARK continuity state and backup/recovery evidence API routes.

Owner-gated: ARK routes require owner authentication — no public access.

R1 MVP — uses in-memory stubs.  Full DB persistence wired to the ark runner
(oc_ark.py from PR #1394) is a follow-up deliverable after that PR merges.

Implements Journey 15: An owner can view system continuity state, see a list
of backup runs with their outcome, inspect evidence for a specific run, and
verify that a restore was tested.

Brain blueprint: OC-ARK-001-autonomous-preservation-recovery-blueprint.md
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.security import verify_owner_or_api_key

from .models import (
    ArkEvidenceResponse,
    ArkRunSummary,
    ArkStatusResponse,
    ContinuityState,
)

router = APIRouter(prefix="/api/ark", tags=["ark"])

Auth = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]

# ---------------------------------------------------------------------------
# In-memory stub store (R1 MVP)
# ---------------------------------------------------------------------------
# Production wiring: replace _RUN_STORE with a DB query against the ark_run
# table populated by oc_ark.py.  The state derivation logic in _derive_state()
# moves to a service layer once persistence lands.
_RUN_STORE: list[ArkRunSummary] = []


def _derive_state(runs: list[ArkRunSummary]) -> ContinuityState:
    """Derive the overall continuity state from the run history.

    Stub logic for R1 MVP:
    - No runs → DISCOVERED (nothing preserved yet)
    - Any run with restore_smoke_ok=True → RESTORE_TESTED (highest safe state)
    - Any run with outcome SUCCESS → VERIFIED
    - Any run present but no success → PROTECTED (something ran, partial)
    """
    if not runs:
        return ContinuityState.DISCOVERED
    if any(r.restore_smoke_ok for r in runs):
        return ContinuityState.RESTORE_TESTED
    if any(r.outcome.value == "SUCCESS" for r in runs):
        return ContinuityState.VERIFIED
    return ContinuityState.PROTECTED


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/status", response_model=ArkStatusResponse)
def get_ark_status(_auth: Auth) -> ArkStatusResponse:
    """Return current continuity state of the OC-ARK system.

    Derives the state from the recorded run history.  With the R1 stub store
    this always returns DISCOVERED until runs are inserted programmatically.
    """
    runs = _RUN_STORE
    state = _derive_state(runs)
    last_run_at = runs[-1].run_at if runs else None
    successful = [r for r in runs if r.outcome.value == "SUCCESS"]
    last_successful_run_at = successful[-1].run_at if successful else None
    restore_tested = any(r.restore_smoke_ok for r in runs)
    return ArkStatusResponse(
        continuity_state=state,
        last_run_at=last_run_at,
        last_successful_run_at=last_successful_run_at,
        run_count=len(runs),
        restore_tested=restore_tested,
    )


@router.get("/runs", response_model=list[ArkRunSummary])
def list_ark_runs(
    _auth: Auth,
    limit: int = 50,
    offset: int = 0,
) -> list[ArkRunSummary]:
    """Return a paginated list of ARK run summaries, newest first.

    Stub returns an empty list in R1.  Full implementation queries the
    ark_run persistence table and joins outcome evidence.
    """
    runs = list(reversed(_RUN_STORE))
    return runs[offset : offset + limit]


@router.get("/evidence/{run_id}", response_model=ArkEvidenceResponse)
def get_ark_evidence(run_id: str, _auth: Auth) -> ArkEvidenceResponse:
    """Return detailed evidence for a specific ARK run, including SHA-256 manifest.

    Returns 404 when the run_id is not found in the store.  In R1 the stub
    store is empty so every call returns 404.
    """
    run = next((r for r in _RUN_STORE if r.run_id == run_id), None)
    if run is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ARK_RUN_NOT_FOUND", "run_id": run_id},
        )
    return ArkEvidenceResponse(
        run_id=run_id,
        sha256_manifest={},
        restore_log=None,
        run_details=run,
    )
