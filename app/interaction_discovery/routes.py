"""Public read-only API for review-bound ecological interaction discovery.

See app.interaction_discovery.service for the ingestion/consumer contract
this surface fulfills. Read-only and public: consistent with other public
species/taxonomy data surfaces in this codebase, and every result is
explicitly labeled as an unverified candidate, not a verified Knowledge
Graph edge, so nothing here can be mistaken for governed scientific fact.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from app.interaction_discovery.service import discover_interactions

router = APIRouter(prefix="/api/interactions", tags=["interaction-discovery"])


@router.get("/discovery")
def get_interaction_discovery(
    taxon: str | None = Query(default=None, max_length=200),
    category: Literal["pollinator", "mycorrhizal", "all"] = Query(default="all"),
    limit: int = Query(default=100, ge=1, le=500),
):
    return discover_interactions(taxon=taxon, category=category, limit=limit)
