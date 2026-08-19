from __future__ import annotations

import time
from typing import Any

import requests

from app.calyx_conversation.interaction_discovery_ingest import (
    ingest_globi_interactions_for_research,
)

GLOBI_INTERACTION_URL = "https://api.globalbioticinteractions.org/interaction"
_FIELDS = (
    "source_taxon_name",
    "source_taxon_external_id",
    "interaction_type",
    "target_taxon_name",
    "target_taxon_external_id",
    "study_citation",
    "study_source_citation",
    "study_external_id",
)


def _bucket_for_time(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // 900)


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "results", "Result", "interactions"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        # Some API representations return a single denormalized row.
        if any(key in payload for key in ("source_taxon_name", "sourceTaxonName")):
            return [payload]
    return []


def harvest_interactions_once(*, limit: int = 20, now: float | None = None) -> dict[str, Any]:
    """Discover review-bound Orchidaceae interaction candidates from GloBI.

    The live Web API is used for exploratory freshness only. GloBI's versioned
    stable dataset remains the required source for a later reproducible bulk
    research backfill. This lane never publishes graph edges automatically.
    """
    bucket = _bucket_for_time(now)
    if bucket % 4 != 0:
        return {
            "status": "not_due",
            "provider": "Global Biotic Interactions",
            "indexed": 0,
        }

    page_size = max(1, min(int(limit), 25))
    page_index = (bucket // 4) % 40
    offset = page_index * page_size
    role = "source" if (bucket // 4) % 2 == 0 else "target"
    params: dict[str, Any] = {
        "type": "json.v2",
        "includeObservations": "true",
        "limit": page_size,
        "offset": offset,
        "fields": ",".join(_FIELDS),
    }
    params["sourceTaxon" if role == "source" else "targetTaxon"] = "Orchidaceae"

    response = requests.get(
        GLOBI_INTERACTION_URL,
        params=params,
        timeout=20,
        headers={"User-Agent": "OrchidContinuum-Calyx/1.0", "Accept": "application/json"},
    )
    response.raise_for_status()
    rows = _records(response.json())
    ingest = ingest_globi_interactions_for_research(rows, query_role=role)
    return {
        "status": ingest.get("status", "completed"),
        "provider": "Global Biotic Interactions",
        "query_role": role,
        "offset": offset,
        "discovered": len(rows),
        "indexed": int(ingest.get("indexed") or 0),
        "review_required": True,
        "stable_research_snapshot_preferred": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
        "ingest": ingest,
    }
