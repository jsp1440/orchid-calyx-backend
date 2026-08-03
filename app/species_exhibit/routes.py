from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .service import build_species_exhibit

router = APIRouter(prefix="/api/platform/homepage", tags=["species-exhibit"])


@router.get("/genus/{genus}/species-exhibit")
def species_exhibit(genus: str, limit: int = Query(9, ge=1, le=24)) -> dict[str, Any]:
    candidate = " ".join((genus or "").strip().split())
    if not re.fullmatch(r"[A-Za-z-]+", candidate):
        raise HTTPException(status_code=400, detail="Genus must contain letters or hyphens only.")
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="Species evidence database is not configured.")
    try:
        result = build_species_exhibit(dsn, candidate, limit)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Species evidence packet service is unavailable.") from exc
    if not result["items"]:
        raise HTTPException(status_code=404, detail="No canonical species were found for this genus.")
    return result
