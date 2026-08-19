from __future__ import annotations

import os
import time
from typing import Any

import requests

from app.calyx_conversation.external_literature import (
    EUROPE_PMC_SEARCH_URL,
    _record_from_europe_pmc,
)
from app.calyx_conversation.historical_fulltext_ingest import (
    ingest_bhl_item_fulltext_for_research,
)
from app.calyx_conversation.historical_literature_ingest import (
    ingest_bhl_publications_for_research,
)
from app.calyx_conversation.literature_ingest import ingest_external_literature_for_research
from app.calyx_conversation.scholarly_metadata_ingest import (
    ingest_crossref_works_for_research,
)
from app.harvest.plugins.bhl.client import BHLClient

BHL_API_URL = "https://www.biodiversitylibrary.org/api3"
CROSSREF_WORKS_URL = "https://api.crossref.org/works"

LITERATURE_TOPICS: tuple[tuple[str, str], ...] = (
    ("orchid_pollination", '(orchid OR Orchidaceae) AND (pollination OR pollinator OR "floral morphology")'),
    ("orchid_mycorrhiza", '(orchid OR Orchidaceae) AND (mycorrhiza OR mycorrhizal OR fungi OR fungal)'),
    ("orchid_traits_ecology", '(orchid OR Orchidaceae) AND (trait OR ecology OR epiphyte OR terrestrial)'),
    ("plant_respiration_photosynthesis", '(plant OR plants) AND (respiration OR photosynthesis OR "carbon metabolism")'),
    ("plant_water_relations", '(plant OR plants) AND ("water relations" OR drought OR waterlogging OR stomata)'),
    ("plant_nutrition_physiology", '(plant OR plants) AND ("mineral nutrition" OR nitrogen OR phosphorus OR nutrient)'),
    ("plant_hormones_development", '(plant OR plants) AND (auxin OR cytokinin OR gibberellin OR "abscisic acid" OR development)'),
    ("plant_genetics_genomics", '(plant OR plants) AND (genetics OR genomics OR transcriptomics OR epigenetics)'),
    ("plant_cell_molecular_biology", '(plant OR plants) AND ("cell biology" OR "molecular biology" OR signaling OR membrane)'),
    ("plant_biochemistry_metabolomics", '(plant OR plants) AND (biochemistry OR metabolomics OR proteomics OR "secondary metabolites")'),
    ("plant_pigments_chemistry", '(plant OR plants) AND (anthocyanin OR flavonoid OR pigment OR carotenoid)'),
    ("plant_reproductive_biology", '(plant OR plants) AND ("reproductive biology" OR pollen OR fertilization OR flowering)'),
    ("plant_fungal_interactions", '(plant OR plants) AND (fungi OR fungal OR mycorrhiza OR symbiosis)'),
    ("plant_evolution_ecology", '(plant OR plants) AND (evolution OR ecology OR adaptation OR phylogeny)'),
    ("plant_conservation", '(plant OR plants) AND (conservation OR extinction OR restoration OR reintroduction)'),
    ("plant_analytical_methods", '(plant OR plants) AND (chromatography OR spectroscopy OR microscopy OR metabolite)'),
)

CROSSREF_TOPICS: tuple[str, ...] = (
    "orchid pollination floral morphology",
    "orchid mycorrhiza fungal symbiosis",
    "Orchidaceae traits ecology",
    "plant respiration photosynthesis physiology",
    "plant water relations stomatal physiology",
    "plant mineral nutrition physiology",
    "plant hormone signaling development",
    "plant genetics genomics transcriptomics",
    "plant cell molecular biology",
    "plant biochemistry metabolomics",
    "plant anthocyanin flavonoid pigments",
    "plant reproductive biology pollen fertilization",
    "plant fungal interactions mycorrhiza",
    "plant evolution ecology adaptation phylogeny",
    "plant conservation restoration reintroduction",
    "plant chromatography spectroscopy analytical methods",
)

BHL_TOPICS: tuple[str, ...] = (
    "Charles Darwin orchids fertilisation",
    "orchid pollination",
    "Orchidaceae",
    "orchid mycorrhiza",
    "orchid physiology",
    "plant physiology",
    "botanical morphology",
    "orchid monograph",
)


def _bucket_for_time(now: float | None = None) -> int:
    timestamp = time.time() if now is None else now
    return int(timestamp // 900)


def _topic_for_time(now: float | None = None) -> tuple[str, str]:
    bucket = _bucket_for_time(now)
    return LITERATURE_TOPICS[bucket % len(LITERATURE_TOPICS)]


def _direct_search(query: str, *, limit: int) -> list[dict[str, Any]]:
    timeout = max(1.0, min(float(os.getenv("CALYX_EXTERNAL_LITERATURE_TIMEOUT_SECONDS", "12")), 30.0))
    page_size = max(1, min(int(limit), 10))
    response = requests.get(
        EUROPE_PMC_SEARCH_URL,
        params={"query": query, "resultType": "core", "pageSize": page_size, "format": "json"},
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
        record["relevance_score"] = None
        records.append(record)
    return records


def _harvest_crossref_once(*, bucket: int, limit: int) -> dict[str, Any]:
    if bucket % 2 != 0:
        return {"status": "not_due", "provider": "Crossref", "indexed": 0}
    query = CROSSREF_TOPICS[(bucket // 2) % len(CROSSREF_TOPICS)]
    timeout = max(1.0, min(float(os.getenv("CALYX_CROSSREF_TIMEOUT_SECONDS", "12")), 30.0))
    page_size = max(1, min(int(limit), 5))
    mailto = os.getenv("CROSSREF_MAILTO", "").strip()
    params: dict[str, Any] = {"query.bibliographic": query, "rows": page_size}
    if mailto:
        params["mailto"] = mailto
    user_agent = "OrchidContinuum-Calyx/1.0" + (f" (mailto:{mailto})" if mailto else "")
    response = requests.get(
        CROSSREF_WORKS_URL,
        params=params,
        timeout=timeout,
        headers={"User-Agent": user_agent, "Accept": "application/json"},
    )
    response.raise_for_status()
    payload = response.json()
    message = payload.get("message") if isinstance(payload, dict) else {}
    raw_items = message.get("items") if isinstance(message, dict) else []
    records = [item for item in (raw_items or []) if isinstance(item, dict)][:page_size]
    ingest = ingest_crossref_works_for_research(records, query=query)
    return {
        "status": ingest.get("status", "completed"),
        "provider": "Crossref",
        "query": query,
        "discovered": len(records),
        "indexed": int(ingest.get("indexed") or 0),
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
        "ingest": ingest,
    }


def _harvest_bhl_once(*, bucket: int, limit: int) -> dict[str, Any]:
    api_key = os.getenv("BHL_API_KEY", "").strip()
    if not api_key:
        return {"status": "not_configured", "provider": "Biodiversity Heritage Library", "required_environment": "BHL_API_KEY", "indexed": 0}
    if bucket % 4 != 0:
        return {"status": "not_due", "provider": "Biodiversity Heritage Library", "indexed": 0}

    query = BHL_TOPICS[(bucket // 4) % len(BHL_TOPICS)]
    timeout = max(1.0, min(float(os.getenv("CALYX_BHL_TIMEOUT_SECONDS", "15")), 30.0))
    page_size = max(1, min(int(limit), 5))
    response = requests.get(
        BHL_API_URL,
        params={"op": "PublicationSearch", "searchterm": query, "searchtype": "F", "page": 1, "pageSize": page_size, "format": "json", "apikey": api_key},
        timeout=timeout,
        headers={"User-Agent": "OrchidContinuum-Calyx/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    status = str(payload.get("Status") or "ok").casefold()
    if status not in {"ok", "success"}:
        raise RuntimeError(str(payload.get("ErrorMessage") or "BHL API error"))
    raw_records = payload.get("Result") or []
    records = [item for item in raw_records if isinstance(item, dict)][:page_size]
    ingest = ingest_bhl_publications_for_research(records, query=query)
    return {
        "status": ingest.get("status", "completed"),
        "provider": "Biodiversity Heritage Library",
        "query": query,
        "discovered": len(records),
        "indexed": int(ingest.get("indexed") or 0),
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
        "ingest": ingest,
    }


def _first_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), None)
    return None


def _harvest_bhl_fulltext_once(*, bucket: int, limit: int) -> dict[str, Any]:
    """Acquire at most two BHL OCR pages using full-text page search.

    This is deliberately less frequent than metadata discovery and never publishes
    OCR directly. Each page is indexed as exact, review-bound historical evidence.
    """
    api_key = os.getenv("BHL_API_KEY", "").strip()
    if not api_key:
        return {"status": "not_configured", "provider": "Biodiversity Heritage Library OCR", "required_environment": "BHL_API_KEY", "indexed": 0}
    if bucket % 8 != 0:
        return {"status": "not_due", "provider": "Biodiversity Heritage Library OCR", "indexed": 0}

    query = BHL_TOPICS[(bucket // 8) % len(BHL_TOPICS)]
    client = BHLClient(api_key=api_key)
    search = client.page_search(search_term=query, page=1)
    raw = search.get("Result") or []
    candidates = [raw] if isinstance(raw, dict) else [item for item in raw if isinstance(item, dict)]
    page_limit = max(1, min(int(limit), 2))
    indexed = 0
    hydrated = 0
    ingest_results: list[dict[str, Any]] = []

    for candidate in candidates[:page_limit]:
        page_id = candidate.get("PageID") or candidate.get("PageId")
        if page_id in (None, ""):
            continue
        metadata = client.page_metadata(int(page_id))
        page = _first_mapping(metadata.get("Result"))
        if page is None:
            continue
        hydrated += 1
        pseudo_item = {
            "ItemID": page.get("ItemID") or page.get("ItemId") or f"page-{page_id}",
            "Title": page.get("Title") or candidate.get("Title") or "BHL historical botanical work",
            "ItemUrl": page.get("ItemUrl") or candidate.get("ItemUrl"),
            "Rights": page.get("Rights") or candidate.get("Rights"),
            "LicenseUrl": page.get("LicenseUrl") or candidate.get("LicenseUrl"),
            "Pages": [page],
        }
        result = ingest_bhl_item_fulltext_for_research(pseudo_item, query=query, max_pages=1)
        indexed += int(result.get("indexed") or 0)
        ingest_results.append(result)

    return {
        "status": "indexed_for_research" if indexed else ("nothing_indexable" if hydrated else "empty"),
        "provider": "Biodiversity Heritage Library OCR",
        "query": query,
        "discovered": len(candidates),
        "hydrated": hydrated,
        "indexed": indexed,
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
        "ingest": ingest_results,
    }


def harvest_literature_once(*, limit: int = 5, now: float | None = None) -> dict[str, Any]:
    """Harvest modern evidence, DOI metadata, historical metadata, and bounded OCR."""
    bucket = _bucket_for_time(now)
    topic, query = _topic_for_time(now)
    records = _direct_search(query, limit=max(1, min(int(limit), 10)))
    ingest = ingest_external_literature_for_research(records, query=query)

    try:
        crossref = _harvest_crossref_once(bucket=bucket, limit=limit)
    except Exception as exc:
        crossref = {"status": "failed", "provider": "Crossref", "error": f"{type(exc).__name__}: {exc}", "indexed": 0}

    try:
        historical = _harvest_bhl_once(bucket=bucket, limit=limit)
    except Exception as exc:
        historical = {"status": "failed", "provider": "Biodiversity Heritage Library", "error": f"{type(exc).__name__}: {exc}", "indexed": 0}

    try:
        historical_fulltext = _harvest_bhl_fulltext_once(bucket=bucket, limit=limit)
    except Exception as exc:
        historical_fulltext = {"status": "failed", "provider": "Biodiversity Heritage Library OCR", "error": f"{type(exc).__name__}: {exc}", "indexed": 0}

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
        "scholarly_metadata": crossref,
        "historical_books": historical,
        "historical_fulltext": historical_fulltext,
        "ingest": ingest,
    }
