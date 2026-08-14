from __future__ import annotations

import os
import time
from typing import Any

import requests

from app.calyx_conversation.external_literature import (
    EUROPE_PMC_SEARCH_URL,
    _record_from_europe_pmc,
)
from app.calyx_conversation.literature_ingest import ingest_external_literature_for_research


# Rotating corpus deliberately mixes Orchidaceae-specific evidence with the
# foundational plant sciences Calyx needs for mechanistic reasoning. Literature
# harvesting is independent of occurrence/image progress so it cannot starve
# behind GBIF or iNaturalist backfills.
LITERATURE_TOPICS: tuple[tuple[str, str], ...] = (
    (
        "orchid_pollination",
        '(orchid OR Orchidaceae) AND (pollination OR pollinator OR "floral morphology")',
    ),
    (
        "orchid_mycorrhiza",
        '(orchid OR Orchidaceae) AND (mycorrhiza OR mycorrhizal OR fungi OR fungal)',
    ),
    (
        "orchid_traits_ecology",
        '(orchid OR Orchidaceae) AND (trait OR ecology OR epiphyte OR terrestrial)',
    ),
    (
        "plant_respiration_photosynthesis",
        '(plant OR plants) AND (respiration OR photosynthesis OR "carbon metabolism")',
    ),
    (
        "plant_water_relations",
        '(plant OR plants) AND ("water relations" OR drought OR waterlogging OR stomata)',
    ),
    (
        "plant_nutrition_physiology",
        '(plant OR plants) AND ("mineral nutrition" OR nitrogen OR phosphorus OR nutrient)',
    ),
    (
        "plant_hormones_development",
        '(plant OR plants) AND (auxin OR cytokinin OR gibberellin OR "abscisic acid" OR development)',
    ),
    (
        "plant_genetics_genomics",
        '(plant OR plants) AND (genetics OR genomics OR transcriptomics OR epigenetics)',
    ),
    (
        "plant_cell_molecular_biology",
        '(plant OR plants) AND ("cell biology" OR "molecular biology" OR signaling OR membrane)',
    ),
    (
        "plant_biochemistry_metabolomics",
        '(plant OR plants) AND (biochemistry OR metabolomics OR proteomics OR "secondary metabolites")',
    ),
    (
        "plant_pigments_chemistry",
        '(plant OR plants) AND (anthocyanin OR flavonoid OR pigment OR carotenoid)',
    ),
    (
        "plant_reproductive_biology",
        '(plant OR plants) AND ("reproductive biology" OR pollen OR fertilization OR flowering)',
    ),
    (
        "plant_fungal_interactions",
        '(plant OR plants) AND (fungi OR fungal OR mycorrhiza OR symbiosis)',
    ),
    (
        "plant_evolution_ecology",
        '(plant OR plants) AND (evolution OR ecology OR adaptation OR phylogeny)',
    ),
    (
        "plant_conservation",
        '(plant OR plants) AND (conservation OR extinction OR restoration OR reintroduction)',
    ),
    (
        "plant_analytical_methods",
        '(plant OR plants) AND (chromatography OR spectroscopy OR microscopy OR metabolite)',
    ),
)


def _topic_for_time(now: float | None = None) -> tuple[str, str]:
    # One deterministic topic per 15-minute bucket. This survives restarts
    # without requiring another scheduler/state table and rotates through the
    # full corpus every four hours at the default cadence.
    timestamp = time.time() if now is None else now
    bucket = int(timestamp // 900)
    return LITERATURE_TOPICS[bucket % len(LITERATURE_TOPICS)]


def _direct_search(query: str, *, limit: int) -> list[dict[str, Any]]:
    timeout = max(
        1.0,
        min(float(os.getenv("CALYX_EXTERNAL_LITERATURE_TIMEOUT_SECONDS", "12")), 30.0),
    )
    page_size = max(1, min(int(limit), 10))
    response = requests.get(
        EUROPE_PMC_SEARCH_URL,
        params={
            "query": query,
            "resultType": "core",
            "pageSize": page_size,
            "format": "json",
        },
        timeout=timeout,
        headers={"User-Agent": "OrchidContinuum-Calyx/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    raw_records = ((payload.get("resultList") or {}).get("result") or [])[:page_size]
    records: list[dict[str, Any]] = []
    for raw in raw_records:
        if not isinstance(raw, dict):
            continue
        record = _record_from_europe_pmc(raw, query=query)
        # Direct corpus harvesting does not claim question-specific relevance;
        # it only stages evidence for governed research use.
        record["relevance_score"] = None
        records.append(record)
    return records


def harvest_literature_once(*, limit: int = 5, now: float | None = None) -> dict[str, Any]:
    """Harvest one bounded literature topic into the governed research index."""

    topic, query = _topic_for_time(now)
    records = _direct_search(query, limit=max(1, min(int(limit), 10)))
    ingest = ingest_external_literature_for_research(records, query=query)
    return {
        "status": ingest.get("status", "completed"),
        "topic": topic,
        "query": query,
        "provider": "Europe PMC",
        "discovered": len(records),
        "indexed": int(ingest.get("indexed") or 0),
        "evidence_set_id": ingest.get("evidence_set_id"),
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
        "ingest": ingest,
    }
