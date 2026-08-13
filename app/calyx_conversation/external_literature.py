from __future__ import annotations

import os
import re
from typing import Any

import requests

EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

_ORCHID_GENERA = (
    "Cymbidium",
    "Cattleya",
    "Laelia",
    "Dendrobium",
    "Sarcochilus",
    "Phalaenopsis",
    "Paphiopedilum",
    "Phragmipedium",
    "Epidendrum",
    "Sobralia",
    "Masdevallia",
    "Lycaste",
)
_TOPIC_TERMS = (
    "flowering",
    "flower",
    "floral",
    "induction",
    "dormancy",
    "rest",
    "keiki",
    "temperature",
    "cold",
    "drought",
    "water",
    "wetness",
    "root",
    "rot",
    "pathogen",
    "physiology",
    "hormone",
    "photoperiod",
    "silicon",
    "thiamine",
    "vitamin",
    "nutrition",
    "foliar",
)


def _query_plan(question: str, *, max_queries: int = 6) -> list[str]:
    """Build short Europe PMC queries from a long natural-language Calyx prompt."""

    normalized = question.casefold()
    genera = [genus for genus in _ORCHID_GENERA if genus.casefold() in normalized]
    topics = [
        term
        for term in _TOPIC_TERMS
        if re.search(rf"\b{re.escape(term)}\w*\b", normalized)
    ]
    topic_expr = " OR ".join(sorted(set(topics[:7])))
    if topic_expr:
        topic_expr = f"({topic_expr})"

    queries: list[str] = []
    ordered_genera = sorted(
        genera,
        key=lambda value: (
            value not in {"Dendrobium", "Sarcochilus"},
            genera.index(value),
        ),
    )
    for genus in ordered_genera[:4]:
        queries.append(f'"{genus}" AND {topic_expr}' if topic_expr else f'"{genus}"')

    if topic_expr:
        queries.append(f'(orchid OR Orchidaceae) AND {topic_expr}')
    queries.append(question[:350])

    deduplicated: list[str] = []
    seen: set[str] = set()
    for value in queries:
        compact = " ".join(value.split()).strip()
        key = compact.casefold()
        if compact and key not in seen:
            seen.add(key)
            deduplicated.append(compact)
        if len(deduplicated) >= max_queries:
            break
    return deduplicated


def _record_from_europe_pmc(record: dict[str, Any], *, query: str) -> dict[str, Any]:
    title = str(record.get("title") or "Untitled publication").strip()
    abstract = str(record.get("abstractText") or "").strip()
    authors = str(record.get("authorString") or "").strip()
    journal = str(record.get("journalTitle") or "").strip()
    journal_info = (
        record.get("journalInfo") if isinstance(record.get("journalInfo"), dict) else {}
    )
    publication_date = str(
        record.get("firstPublicationDate")
        or journal_info.get("printPublicationDate")
        or ""
    ).strip()
    doi = str(record.get("doi") or "").strip() or None
    pmid = str(record.get("pmid") or record.get("id") or "").strip() or None
    pmcid = str(record.get("pmcid") or "").strip() or None
    return {
        "title": title,
        "authors": authors,
        "journal": journal,
        "publication_date": publication_date,
        "doi": doi,
        "pmid": pmid,
        "pmcid": pmcid,
        "abstract": abstract[:3000],
        "matched_query": query,
        "source": "Europe PMC",
        "source_url": EUROPE_PMC_SEARCH_URL,
        "external": True,
        "review_state": "REVIEW_REQUIRED",
        "canonical_evidence": False,
    }


def search_europe_pmc(query: str, *, limit: int = 8) -> dict[str, Any]:
    """Discover external literature when the local Continuum index has no coverage.

    Long prompts are decomposed into short targeted searches. All returned records
    remain external/review-required until intentionally indexed and reviewed.
    """

    timeout = max(
        1.0,
        min(float(os.getenv("CALYX_EXTERNAL_LITERATURE_TIMEOUT_SECONDS", "12")), 30.0),
    )
    result_limit = max(1, min(int(limit), 25))
    query_plan = _query_plan(query)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    diagnostics: list[dict[str, Any]] = []

    for planned_query in query_plan:
        if len(results) >= result_limit:
            break
        page_size = min(max(4, result_limit), 15)
        try:
            response = requests.get(
                EUROPE_PMC_SEARCH_URL,
                params={
                    "query": planned_query,
                    "resultType": "core",
                    "pageSize": page_size,
                    "format": "json",
                },
                timeout=timeout,
                headers={"User-Agent": "OrchidContinuum-Calyx/1.0"},
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            diagnostics.append({"query": planned_query, "error": str(exc)})
            continue

        records = ((payload.get("resultList") or {}).get("result") or [])[:page_size]
        for raw in records:
            if not isinstance(raw, dict):
                continue
            record = _record_from_europe_pmc(raw, query=planned_query)
            identity = str(
                record.get("doi") or record.get("pmid") or record.get("title") or ""
            ).casefold()
            if not identity or identity in seen:
                continue
            seen.add(identity)
            results.append(record)
            if len(results) >= result_limit:
                break

    return {
        "provider": "Europe PMC",
        "query": query[:500],
        "query_plan": query_plan,
        "results": results,
        "result_count": len(results),
        "diagnostics": diagnostics,
        "external": True,
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


def augment_retrieval_with_external_literature(
    retrieval: dict[str, Any],
    query: str,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    """Attach Europe PMC discovery when local retrieval cannot answer."""

    result = dict(retrieval)
    local_results = result.get("results") or []
    original_status = str(result.get("status") or "available")
    force = os.getenv("CALYX_EXTERNAL_LITERATURE_ALWAYS", "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if local_results and not force:
        result.setdefault(
            "external_literature",
            {
                "provider": "Europe PMC",
                "results": [],
                "result_count": 0,
                "status": "not_needed_local_coverage_available",
                "external": True,
                "review_required": True,
            },
        )
        return result

    try:
        external = search_europe_pmc(query, limit=limit)
        external["status"] = "available" if external.get("results") else "empty"
    except (requests.RequestException, ValueError, TypeError) as exc:
        external = {
            "provider": "Europe PMC",
            "results": [],
            "result_count": 0,
            "status": "unavailable",
            "error": str(exc),
            "external": True,
            "review_required": True,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        }
    result["external_literature"] = external
    if (
        external.get("results")
        and not local_results
        and original_status not in {"unavailable", "degraded", "error"}
    ):
        result["status"] = "local_empty_external_literature_available"
    return result
