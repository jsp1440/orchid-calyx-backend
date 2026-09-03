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

# Lowercase words that look like potential genus names but are not botanical.
# Filtering prevents generic English words from being treated as taxa.
_NON_TAXON_WORDS = frozenset(
    {
        "the",
        "and",
        "orchid",
        "family",
        "species",
        "genus",
        "plant",
        "flower",
        "root",
        "leaf",
        "stem",
        "orchidaceae",
        "biology",
        "botany",
        "science",
        "research",
        "study",
        "common",
        "native",
        "tropical",
        "temperate",
        "alpine",
        "winter",
        "summer",
        "spring",
        "autumn",
        "fall",
        "please",
        "what",
        "where",
        "how",
        "why",
        "which",
        "tell",
        "about",
        "calyx",
        "continuum",
    }
)

_PHYSIOLOGY_CLUSTERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "seasonal_flowering",
        (
            "flowering",
            "floral induction",
            "flower induction",
            "flower bud",
            "floral bud",
            "dormancy",
            "winter rest",
        ),
    ),
    (
        "temperature",
        (
            "temperature",
            "low temperature",
            "cool temperature",
            "cold treatment",
            "chilling",
            "night temperature",
            "thermoperiod",
        ),
    ),
    (
        "water_rest",
        (
            "drought",
            "water deficit",
            "water stress",
            "dry season",
            "dry rest",
            "watering",
            "moisture",
        ),
    ),
    (
        "developmental_fate",
        (
            "keiki",
            "vegetative propagation",
            "axillary bud",
            "adventitious shoot",
            "vegetative growth",
        ),
    ),
    (
        "regulation",
        (
            "hormone",
            "gibberellin",
            "cytokinin",
            "auxin",
            "abscisic acid",
            "photoperiod",
            "carbohydrate",
            "flowering gene",
        ),
    ),
    (
        "wetness_pathology",
        (
            "root rot",
            "black rot",
            "Phytophthora",
            "Pythium",
            "soft rot",
            "waterlogging",
            "hypoxia",
            "anoxia",
            "leaf wetness",
            "crown rot",
        ),
    ),
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

_WET_WINTER_TERMS = (
    "wet winter",
    "very wet winter",
    "winter rain",
    "rainfall",
    "rain",
    "prolonged wet",
    "persistent moisture",
    "root-zone moisture",
    "waterlogging",
    "saturated",
    "saturation",
    "root rot",
    "crown wetness",
    "leaf wetness",
    "el niño",
    "el nino",
)

_FLOWERING_TERMS = (
    "flower",
    "flowering",
    "bloom",
    "floral induction",
    "keiki",
    "winter rest",
    "dormancy",
)


def _extract_potential_genera(text: str) -> list[str]:
    """Extract capitalized words from text that resemble botanical genus names.

    Accepts any word that:
    - Starts with an uppercase letter followed by lowercase letters (Title case)
    - Is at least 4 characters long
    - Is not in the non-taxon stopword list
    - Appears in a binomial context (word followed by a lowercase word, suggesting
      a species epithet) OR appears to be a standalone capitalized botanical word

    Returns deduplicated list preserving first-seen order.
    """
    # Binomial pattern: "Genus species" — capitalized genus followed by lowercase epithet
    binomial_re = re.compile(r"\b([A-Z][a-z]{2,})\s+[a-z]{2,}")
    # Also catch isolated capitalized words that look like genera (≥5 chars, Title case)
    isolated_re = re.compile(r"\b([A-Z][a-z]{4,})\b")

    seen: dict[str, str] = {}
    for match in binomial_re.finditer(text):
        word = match.group(1)
        key = word.casefold()
        if key not in _NON_TAXON_WORDS and key not in seen:
            seen[key] = word

    for match in isolated_re.finditer(text):
        word = match.group(1)
        key = word.casefold()
        if key not in _NON_TAXON_WORDS and key not in seen:
            seen[key] = word

    return list(seen.values())


def _mentioned_genera(question: str, extra_taxa: list[str] | None = None) -> list[str]:
    """Return genera mentioned in the question.

    Combines:
    1. The canonical hardcoded genus list (for known well-studied orchid genera)
    2. Any potential genus names extracted from the question text
    3. Any genera from explicit taxa supplied by the caller (e.g. ["Calypso bulbosa"])

    Preserves order: hardcoded matches first, then extracted, then explicit.
    Deduplicates case-insensitively.
    """
    normalized = question.casefold()
    seen: set[str] = set()
    result: list[str] = []

    # 1. Hardcoded canonical genera
    for genus in _ORCHID_GENERA:
        if re.search(rf"\b{re.escape(genus.casefold())}\b", normalized):
            key = genus.casefold()
            if key not in seen:
                seen.add(key)
                result.append(genus)

    # 2. Potential genera extracted from the question text itself
    for genus in _extract_potential_genera(question):
        key = genus.casefold()
        if key not in seen:
            seen.add(key)
            result.append(genus)

    # 3. Genera from explicit taxa supplied by the caller
    if extra_taxa:
        for taxon in extra_taxa:
            # Treat first word of each taxon as the genus
            parts = str(taxon or "").strip().split()
            if not parts:
                continue
            genus = parts[0]
            if not genus[0].isupper():
                continue
            key = genus.casefold()
            if key not in seen and key not in _NON_TAXON_WORDS:
                seen.add(key)
                result.append(genus)

    return result


def _wet_winter_intent(question: str) -> bool:
    normalized = " ".join(question.casefold().split())
    return any(term in normalized for term in _WET_WINTER_TERMS)


def _flowering_intent(question: str) -> bool:
    normalized = " ".join(question.casefold().split())
    return any(term in normalized for term in _FLOWERING_TERMS)


def _cluster(name: str) -> tuple[str, tuple[str, ...]]:
    return next(item for item in _PHYSIOLOGY_CLUSTERS if item[0] == name)


def _active_clusters(question: str) -> list[tuple[str, tuple[str, ...]]]:
    normalized = question.casefold()
    active: list[tuple[str, tuple[str, ...]]] = []
    for name, terms in _PHYSIOLOGY_CLUSTERS:
        if any(term.casefold() in normalized for term in terms):
            active.append((name, terms))

    if _wet_winter_intent(question):
        preferred = (
            _cluster("wetness_pathology"),
            _cluster("temperature"),
            _cluster("water_rest"),
        )
        for item in reversed(preferred):
            if item in active:
                active.remove(item)
            active.insert(0, item)

    if _flowering_intent(question):
        for name in ("seasonal_flowering", "developmental_fate", "regulation"):
            item = _cluster(name)
            if item not in active:
                active.append(item)

    if not active and "winter" in normalized:
        active.extend(
            (
                _cluster("temperature"),
                _cluster("water_rest"),
                _cluster("wetness_pathology"),
            )
        )
    return active


def _epmc_or(terms: tuple[str, ...], *, limit: int = 5) -> str:
    values = [f'"{value}"' if " " in value else value for value in terms[:limit]]
    return " OR ".join(values)


def _query_plan(
    question: str,
    *,
    max_queries: int = 8,
    taxa: list[str] | None = None,
) -> list[str]:
    """Build focused Europe PMC searches from a natural-language Calyx question.

    Args:
        question: Natural-language research question.
        max_queries: Maximum number of query strings to produce.
        taxa: Optional explicit list of scientific names (binomials or genera) to
              include in the plan, e.g. ["Calypso bulbosa", "Pleione humilis"].
              These supplement any taxa detected from the question text.
    """

    genera = _mentioned_genera(question, extra_taxa=taxa)
    clusters = _active_clusters(question)
    wet_winter = _wet_winter_intent(question)
    ordered_genera = sorted(
        genera,
        key=lambda value: (
            value not in {"Dendrobium", "Sarcochilus", "Cymbidium", "Laelia"},
            genera.index(value),
        ),
    )
    queries: list[str] = []

    genus_budget = 5 if wet_winter else 4
    cluster_budget = 2 if wet_winter else 3
    for genus in ordered_genera[:genus_budget]:
        for _, terms in clusters[:cluster_budget]:
            queries.append(f'"{genus}" AND ({_epmc_or(terms)})')
            if len(queries) >= max_queries:
                break
        if len(queries) >= max_queries:
            break

    if wet_winter and len(queries) < max_queries:
        queries.append(
            '(orchid OR Orchidaceae) AND '
            '(waterlogging OR "root rot" OR Phytophthora OR Pythium OR "leaf wetness" OR hypoxia)'
        )

    if len(queries) < max_queries and ordered_genera and _flowering_intent(question):
        regulation = next(
            (terms for name, terms in clusters if name == "regulation"),
            _PHYSIOLOGY_CLUSTERS[4][1],
        )
        for genus in ordered_genera[:2]:
            queries.append(f'"{genus}" AND ({_epmc_or(regulation)})')
            if len(queries) >= max_queries:
                break

    if len(queries) < max_queries:
        combined_terms: list[str] = []
        for _, terms in clusters[:3]:
            combined_terms.extend(terms[:2])
        if combined_terms:
            expr = " OR ".join(
                f'"{term}"' if " " in term else term for term in combined_terms[:6]
            )
            queries.append(f'(orchid OR Orchidaceae) AND ({expr})')

    # Fallback: when no cluster terms fired but genera are present, emit bare
    # genus queries so any taxon produces at least one retrievable plan entry.
    if not queries and ordered_genera:
        for genus in ordered_genera[:max_queries]:
            queries.append(f'"{genus}" AND (orchid OR Orchidaceae OR ecology OR physiology OR cultivation)')
            if len(queries) >= max_queries:
                break

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
        "abstract": abstract[:4000],
        "matched_query": query,
        "source": "Europe PMC",
        "source_url": EUROPE_PMC_SEARCH_URL,
        "external": True,
        "review_state": "REVIEW_REQUIRED",
        "canonical_evidence": False,
    }


def _relevance_score(
    record: dict[str, Any],
    question: str,
    taxa: list[str] | None = None,
) -> float:
    """Rank records for the actual physiological question, not generic orchid match."""

    question_cf = question.casefold()
    title = str(record.get("title") or "").casefold()
    abstract = str(record.get("abstract") or "").casefold()
    text = title + " " + abstract
    mentioned = _mentioned_genera(question, extra_taxa=taxa)
    active = _active_clusters(question)
    wet_winter = _wet_winter_intent(question)

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
        "floral induction",
        "flower induction",
        "low temperature",
        "cold treatment",
        "night temperature",
        "winter rest",
        "dry season",
        "water deficit",
        "dormancy",
        "keiki",
        "axillary bud",
        "flower bud differentiation",
        "flower bud formation",
        "waterlogging",
        "root rot",
        "phytophthora",
        "pythium",
        "hypoxia",
        "leaf wetness",
        "crown rot",
    )
    score += 2.5 * sum(phrase in text for phrase in diagnostic_phrases)

    for distractor in _DISTRACTOR_TERMS:
        if distractor in title and distractor not in question_cf:
            score -= 4.0
        elif distractor in abstract and distractor not in question_cf:
            score -= 1.0

    if wet_winter and not _flowering_intent(question):
        wet_hits = sum(
            term in text
            for term in (
                "waterlogging",
                "root rot",
                "phytophthora",
                "pythium",
                "hypoxia",
                "leaf wetness",
                "crown rot",
                "moisture",
                "rain",
            )
        )
        if wet_hits == 0 and any(
            term in title for term in ("flower", "floral", "reflowering", "pollination")
        ):
            score -= 6.0

    if not abstract.strip():
        score -= 2.0
    return round(score, 3)


def search_europe_pmc(
    query: str,
    *,
    limit: int = 8,
    taxa: list[str] | None = None,
) -> dict[str, Any]:
    """Discover and relevance-rank external literature for a Calyx research turn.

    Args:
        query: Natural-language research question.
        limit: Maximum results to return.
        taxa: Optional explicit list of scientific binomials or genera to include
              in the query plan, e.g. ["Calypso bulbosa", "Pleione humilis"].
              Enables evidence retrieval for any orchid taxon, not just the
              canonical hardcoded genus list.
    """

    timeout = max(
        1.0,
        min(float(os.getenv("CALYX_EXTERNAL_LITERATURE_TIMEOUT_SECONDS", "12")), 30.0),
    )
    result_limit = max(1, min(int(limit), 25))
    query_plan = _query_plan(query, taxa=taxa)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    diagnostics: list[dict[str, Any]] = []

    for planned_query in query_plan:
        page_size = min(max(8, result_limit * 2), 25)
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
            record["relevance_score"] = _relevance_score(record, query, taxa=taxa)
            candidates.append(record)

    candidates.sort(
        key=lambda item: (
            -float(item.get("relevance_score") or 0.0),
            str(item.get("publication_date") or ""),
            str(item.get("title") or ""),
        )
    )
    strong = [
        item for item in candidates if float(item.get("relevance_score") or 0) >= 4.0
    ]
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
    taxa: list[str] | None = None,
) -> dict[str, Any]:
    """Attach discovery and bridge it into the review-bound Brain research index.

    Args:
        retrieval: Local retrieval result dict.
        query: Natural-language research question.
        limit: Maximum external results to return.
        taxa: Optional explicit scientific names to include in query planning,
              e.g. ["Calypso bulbosa", "Pleione humilis"].
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
        external = search_europe_pmc(query, limit=limit, taxa=taxa)
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

    if (
        records
        and not local_results
        and original_status not in {"unavailable", "degraded", "error"}
    ):
        result["status"] = "local_empty_external_literature_available"
    return result
