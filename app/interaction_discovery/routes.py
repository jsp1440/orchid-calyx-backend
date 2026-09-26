"""Public read-only API for review-bound ecological interaction discovery.

See app.interaction_discovery.service for the ingestion/consumer contract
this surface fulfills. Read-only and public: consistent with other public
species/taxonomy data surfaces in this codebase, and every result is
explicitly labeled as an unverified candidate, not a verified Knowledge
Graph edge, so nothing here can be mistaken for governed scientific fact.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field

from app.interaction_discovery.service import discover_interactions

router = APIRouter(prefix="/api/interactions", tags=["interaction-discovery"])


class InteractionDiscoveryRecord(BaseModel):
    # Tolerant by design: records come from semantic-index metadata, so a
    # numeric id or an extra key must not turn a read into a 500.
    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=True)

    source_taxon_name: str | None = None
    source_taxon_id: str | None = None
    target_taxon_name: str | None = None
    target_taxon_id: str | None = None
    interaction_type: str
    categories: list[str]
    study_citation: str | None = None
    study_source_citation: str | None = None
    study_external_id: str | None = None
    provider: str | None = None
    provider_stability: str | None = None
    dataset_version: str | None = None
    verification_state: Literal["UNVERIFIED"]
    knowledge_graph_mutation: Literal[False]
    revision_id: int | None = Field(
        default=None,
        description="Kept for compatibility; may exceed 2^53, use revision_id_str in JavaScript clients.",
    )
    revision_id_str: str | None = Field(
        default=None, description="Exact decimal string form of revision_id."
    )
    locator: dict[str, Any] | None = None


class InteractionDiscoveryResponse(BaseModel):
    status: Literal["ok"]
    count: int
    total_matched: int
    truncated: bool
    category: Literal["pollinator", "mycorrhizal", "all"]
    taxon_filter: str | None = None
    index_state: Literal["durable", "memory_unprovisioned"] = Field(
        description=(
            "Which index served this read. memory_unprovisioned means no durable "
            "interaction index is configured, so an empty result is not evidence "
            "of absence. A configured-but-unreachable durable index returns 503."
        )
    )
    index_note: str | None = None
    review_bound: Literal[True]
    knowledge_graph_mutation: Literal[False]
    note: str
    interactions: list[InteractionDiscoveryRecord]


@router.get("/discovery", response_model=InteractionDiscoveryResponse)
def get_interaction_discovery(
    taxon: str | None = Query(default=None, max_length=200),
    category: Literal["pollinator", "mycorrhizal", "all"] = Query(default="all"),
    limit: int = Query(default=100, ge=1, le=500),
):
    return discover_interactions(taxon=taxon, category=category, limit=limit)
