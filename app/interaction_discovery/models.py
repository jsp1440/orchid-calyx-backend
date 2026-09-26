"""Response contract for the interaction-discovery read surface.

Shared by the route (as ``response_model``) and the service (which validates
each stored record against ``InteractionDiscoveryRecord`` before it is
returned, so a single malformed stored record is excluded and counted rather
than turning the whole list into a 500).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    unreadable_count: int = Field(
        default=0,
        description=(
            "Stored candidate records that matched this query but could not be read "
            "(failed record validation) and were excluded from interactions, count, "
            "total_matched and truncation. Non-zero means this result is incomplete."
        ),
    )
    review_bound: Literal[True]
    knowledge_graph_mutation: Literal[False]
    note: str
    interactions: list[InteractionDiscoveryRecord]
