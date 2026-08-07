from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .portfolio import orchestration_portfolio

router = APIRouter(prefix="/portfolio", tags=["calyx-mission-control"])

DbDependency = Annotated[Session, Depends(get_db)]
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


def _owner(auth: dict[str, Any]) -> str:
    owner = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not owner:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_OWNER_REQUIRED"})
    return owner


@router.get("")
def portfolio(
    auth: AuthDependency,
    db: DbDependency,
    program_id: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    try:
        return orchestration_portfolio(
            db,
            owner=_owner(auth),
            program_id=program_id,
            architecture=architecture,
        )
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
