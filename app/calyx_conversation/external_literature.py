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

_PHYSIOLOGY_CLUSTERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("seasonal_flowering", ("flowering", "floral induction", "flower induction", "flower bud", "floral bud", "dormancy", "winter rest")),
    ("temperature", ("temperature", "low temperature", "cool temperature", "cold treatment", "chilling", "night temperature", "thermoperiod")),
    ("water_rest", ("drought", "water deficit", "water stress", "dry season", "dry rest", "watering", "moisture")),
    ("developmental_fate", ("keiki", "vegetative propagation", "axillary bud", "adventitious shoot", "vegetative growth")),
    ("regulation", ("hormone", "gibberellin", "cytokinin", "auxin", "abscisic acid", "photoperiod", "carbohydrate", "flowering gene")),
    ("wetness_pathology", ("root rot", "black rot", "Phytophthora", "Pythium", "soft rot", "waterlogging", "hypoxia", "anoxia")),
)

_DISTRACTOR_TERMS = (
    "volatile",
    "scent",
    "fragrance",
    "flavonoid",
    "anthocyanin",
    "pigment",
    "flower color",
    "flower colour",
    "pollinator",
    "pollination",
)


def _mentioned_genera(question: str) -> list[str]:
    normalized = question.casefold()
    return [genus for genus in _ORCHID_GENERA if genus.casefold() in normalized]


def _active_clusters(question: str) -> list[tuple[str, tuple[str, ...]]]:
    normalized = question.casefold()
    active: list[tuple[str, tuple[str, ...]]] = []
    for name, terms in _PHYSIOLOGY_CLUSTERS:
        if any(term.casefold() in normalized for term in terms):
            active.append((name, terms))
    if not active and any(word in normalized for word in ("winter", "flower", "bloom")):
        active.extend(_PHYSIOLOGY_CLUSTERS[:3])
    return active


def _epmc_or(terms: tuple[str, ...], *, limit: int = 5) -> str:
    values = [f'"{value}"' if " " in value else value for value in terms[:limit]]
    return " OR ".join(values)


def _query_plan(question: str, *, max_queries: int = 8) -> list[str]:
    """Build focused Europe PMC searches from a natural-language Calyx question."""

    genera = _mentioned_genera(question)
    clusters = _active_clusters(question)
    ordered_genera = sorted(
        genera,
        key=lambda value: (value not in {"Dendrobium", "Sarcochilus"}, genera.index(value)),
    )
    queries: list[str] = []

    for genus in ordered_genera[:4]:
        for _, terms in clusters[:3]:
            queries.append(f'"{genus}" AND ({_epmc_or(terms)})')
            if len(queries) >= max_queries:
                break
        if len(queries) >= max_queries:
            break

    if len(queries) < max_queries and ordered_genera:
        regulation = next((terms for name, terms in clusters if name == "regulation"), _PHYSIOLOGY_CLUSTERS[4][1])
        for genus in ordered_genera[:2]:
            queries.append(f'"{genus}" AND ({_epmc_or(regulation)})')
            if len(queries) >= max_queries:
                break

    if len(queries) < max_queries:
        combined_terms: list[str] = []
        for _, terms in clusters[:3]:
            combined_terms.extend(terms[:2])
        if combined_terms:
            expr = " OR ".join(f'"{term}"' if " " in term else term for term in combined_terms[:6])
            queries.append(f'(orchid OR Orchidaceae) AND ({expr})')

    deduplicated: list[str] = []
    seen: set[str] = set()
    for value in queries:
        compact = " ".join(value.split()).strip()
        key = compact.casefold()
        if compact and key not in seen:
            seen.add(key)
            deduplicated.append(compact[:480])
        if len(deduplicated) >= max_queries:
            break
    return deduplicated


def _record_from_europe_pmc(record: dict[str, Any], *, query: str) -> dict[str, Any]:
    title = str(record.get("title") or "Untitled publication").strip()
    abstract = str(record.get("abstractText") or "").strip()
    authors = str(record.get("authorString") or "").strip()
    journal = str(record.get("journalTitle") or "").strip()
    journal_info = record.get("journalInfo") if isinstance(record.get("journalInfo"), dict) else {}
    publication_date = str(record.get("firstPublicationDate") or journal_info.get("printPublicationDate") or "").strip()
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
        "abstract": abstract[:4000],
        "matched_query": query,
        "source": "Europe PMC",
        "source_url": EUROPE_PMC_SEARCH_URL,
        "external": True,
        "review_state": "REVIEW_REQUIRED",
        "canonical_evidence": False,
    }


def _relevance_score(record: dict[str, Any], question: str) -> float:
    """Rank records for the actual physiological question, not generic orchid match."""

    question_cf = question.casefold()
    title = str(record.get("title") or "").casefold()
    abstract = str(record.get("abstract") or "").casefold()
    text = title + " " + abstract
    mentioned = _mentioned_genera(question)
    active = _active_clusters(question)

    score = 0.0
    matched_genera = [genus for genus in mentioned if genus.casefold() in text]
    if matched_genera:
        score += 7.0 + min(2.0, len(matched_genera) - 1)
    elif "orchid" in text or "orchidaceae" in text:
        score += 1.0
    else:
        score -= 6.0

    for _, terms in active:
        cluster_hits = 0
        for term in terms:
            term_cf = term.casefold()
            if term_cf in title:
                score += 3.0
                cluster_hits += 1
            elif term_cf in abstract:
                score += 1.2
                cluster_hits += 1
        if cluster_hits >= 2:
            score += 2.0

    diagnostic_phrases = (
        "floral induction", "flower induction", "low temperature", "cold treatment",
        "night temperature", "winter rest", "dry season", "water deficit", "dormancy",
        "keiki", "axillary bud", "flower bud differentiation", "flower bud formation",
    )
    score += 2.5 * sum(phrase in text for phrase in diagnostic_phrases)

    for distractor in _DISTRACTOR_TERMS:
        if distractor in title and distractor not in question_cf:
            score -= 4.0
        elif distractor in abstract and distractor not in question_cf:
            score -= 1.0

    if not abstract.strip():
        score -= 2.0
    return round(score, 3)


def search_europe_pmc(query: str, *, limit: int = 8) -> dict[str, Any]:
    """Discover and relevance-rank external literature for a Calyx research turn."""

    timeout = max(1.0, min(float(os.getenv("CALYX_EXTERNAL_LITERATURE_TIMEOUT_SECONDS", "12")), 30.0))
    result_limit = max(1, min(int(limit), 25))
    query_plan = _query_plan(query)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    diagnostics: list[dict[str, Any]] = []

    for planned_query in query_plan:
        page_size = min(max(8, result_limit * 2), 25)
        try:
            response = requests.get(
                EUROPE_PMC_SEARCH_URL,
                params={"query": planned_query, "resultType": "core", "pageSize": page_size, "format": "json"},
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
            identity = str(record.get("doi") or record.get("pmid") or record.get("title") or "").casefold()
            if not identity or identity in seen:
                continue
            seen.add(identity)
            record["relevance_score"] = _relevance_score(record, query)
            candidates.append(record)

    candidates.sort(
        key=lambda item: (
            -float(item.get("relevance_score") or 0.0),
            str(item.get("publication_date") or ""),
            str(item.get("title") or ""),
        )
    )
    strong = [item for item in candidates if float(item.get("relevance_score") or 0) >= 4.0]
    results = (strong if strong else candidates)[:result_limit]

    return {
        "provider": "Europe PMC",
        "query": query[:500],
        "query_plan": query_plan,
        "results": results,
        "result_count": len(results),
        "candidate_count": len(candidates),
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
    """Attach discovery and bridge it into the review-bound Brain research index."""

    result = dict(retrieval)
    local_results = result.get("results") or []
    original_status = str(result.get("status") or "available")
    force = os.getenv("CALYX_EXTERNAL_LITERATURE_ALWAYS", "").strip().casefold() in {"1", "true", "yes", "on"}
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

    records = external.get("results") or []
    if records:
        try:
            from .literature_ingest import ingest_external_literature_for_research

            result["research_index_ingest"] = ingest_external_literature_for_research(
                records, query=query
            )
        except Exception as exc:  # noqa: BLE001 - ingestion degradation cannot hide discovery
            result["research_index_ingest"] = {
                "status": "failed",
                "error": str(exc),
                "review_required": True,
                "automatic_publication": False,
                "knowledge_graph_mutation": False,
            }

    if records and not local_results and original_status not in {"unavailable", "degraded", "error"}:
        result["status"] = "local_empty_external_literature_available"
    return result
