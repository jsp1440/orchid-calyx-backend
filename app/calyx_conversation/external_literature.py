from __future__ import annotations

import os
from typing import Any

import requests

EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def search_europe_pmc(query: str, *, limit: int = 8) -> dict[str, Any]:
    """Discover external literature when the local Continuum index has no coverage.

    Results are deliberately labeled external/review-required. They may inform a
    conversational synthesis, but they are not canonical Orchid Continuum evidence
    and are never auto-promoted into the Knowledge Graph.
    """

    timeout = max(
        1.0,
        min(float(os.getenv("CALYX_EXTERNAL_LITERATURE_TIMEOUT_SECONDS", "12")), 30.0),
    )
    page_size = max(1, min(int(limit), 25))
    response = requests.get(
        EUROPE_PMC_SEARCH_URL,
        params={
            "query": query[:500],
            "resultType": "core",
            "pageSize": page_size,
            "format": "json",
        },
        timeout=timeout,
        headers={"User-Agent": "OrchidContinuum-Calyx/1.0"},
    )
    response.raise_for_status()
    payload = response.json()
    records = ((payload.get("resultList") or {}).get("result") or [])[:page_size]
    results: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        title = str(record.get("title") or "Untitled publication").strip()
        abstract = str(record.get("abstractText") or "").strip()
        authors = str(record.get("authorString") or "").strip()
        journal = str(record.get("journalTitle") or "").strip()
        publication_date = str(
            record.get("firstPublicationDate")
            or record.get("journalInfo", {}).get("printPublicationDate")
            or ""
        ).strip()
        doi = str(record.get("doi") or "").strip() or None
        pmid = str(record.get("pmid") or record.get("id") or "").strip() or None
        pmcid = str(record.get("pmcid") or "").strip() or None
        results.append(
            {
                "title": title,
                "authors": authors,
                "journal": journal,
                "publication_date": publication_date,
                "doi": doi,
                "pmid": pmid,
                "pmcid": pmcid,
                "abstract": abstract[:3000],
                "source": "Europe PMC",
                "source_url": EUROPE_PMC_SEARCH_URL,
                "external": True,
                "review_state": "REVIEW_REQUIRED",
                "canonical_evidence": False,
            }
        )
    return {
        "provider": "Europe PMC",
        "query": query[:500],
        "results": results,
        "result_count": len(results),
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
    """Attach Europe PMC discovery only when local retrieval cannot answer.

    The local evidence index remains authoritative. External records are placed in a
    separate field so callers cannot accidentally describe them as indexed evidence.
    The original local retrieval status is preserved when the local index is degraded
    or unavailable, even if external discovery succeeds.
    """

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
        external["status"] = "available"
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
