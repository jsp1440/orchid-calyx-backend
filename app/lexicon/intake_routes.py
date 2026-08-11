from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.security import verify_owner_or_api_key

from .intake import filter_items, get_item, load_items, validate_manifest

AuthDep = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]
router = APIRouter(prefix="/intake", tags=["illustrated-orchid-lexicon-intake"])


@router.get("/status")
def intake_status(_auth: AuthDep) -> dict[str, Any]:
    return validate_manifest()


@router.get("/items")
def list_intake_items(
    _auth: AuthDep,
    q: str | None = Query(default=None, max_length=300),
    concept_intake_state: str | None = Query(default=None, max_length=80),
    figure_state: str | None = Query(default=None, max_length=80),
    priority: int | None = Query(default=None, ge=0, le=10),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    items = filter_items(
        q=q,
        concept_intake_state=concept_intake_state,
        figure_state=figure_state,
        priority=priority,
        limit=limit,
    )
    return {
        "count": len(items),
        "items": items,
        "total_manifest_items": len(load_items()),
        "read_only": True,
    }


@router.get("/items/{glossary_id}")
def read_intake_item(glossary_id: str, _auth: AuthDep) -> dict[str, Any]:
    item = get_item(glossary_id)
    if item is None:
        raise HTTPException(status_code=404, detail={"code": "LEXICON_INTAKE_ITEM_NOT_FOUND"})
    return {"item": item, "read_only": True}
