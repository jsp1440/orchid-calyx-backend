from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.security import verify_owner_or_api_key
from app.security_audit import OWNER_READINESS_POLICY, SecurityEventLedger, SecurityReadinessService

router = APIRouter(
    prefix="/brain/mission-control/security",
    tags=["mission-control-security"],
)
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]
_ledger = SecurityEventLedger()
_service = SecurityReadinessService(_ledger)


def _actor(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or identity.get("subject") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "SECURITY_OWNER_SCOPE_REQUIRED"})
    return actor


@router.get("/readiness")
def security_readiness(identity: Identity) -> dict[str, Any]:
    actor = _actor(identity)
    if not OWNER_READINESS_POLICY.permits("read_security_readiness"):
        raise HTTPException(status_code=403, detail={"code": "SECURITY_POLICY_DENIED"})
    _ledger.append(actor=actor, event_type="security_readiness_viewed", detail="Owner viewed sanitized security readiness.")
    return _service.readiness()


@router.get("/events")
def security_events(identity: Identity, limit: int = Query(100, ge=1, le=1000)) -> dict[str, Any]:
    _actor(identity)
    if not OWNER_READINESS_POLICY.permits("read_security_events"):
        raise HTTPException(status_code=403, detail={"code": "SECURITY_POLICY_DENIED"})
    return {"items": _ledger.list_events(limit=limit), "immutable": True}
