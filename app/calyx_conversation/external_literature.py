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

# Common English words that appear Title-cased at sentence start but are not genera.
_STOPWORDS_LOWER: frozenset[str] = frozenset({
    "the", "a", "an", "in", "on", "at", "to", "by", "for", "with",
    "from", "this", "that", "these", "those", "it", "is", "was",
    "are", "were", "be", "and", "or", "but", "if", "of", "as",
    "could", "would", "should", "may", "might", "will", "shall",
    "do", "did", "does", "have", "has", "had", "can", "what",
    "which", "who", "how", "when", "where", "why",
    "general", "regional", "seasonal", "another",
    "review", "compare", "tell", "provide", "show", "explain",
    "orchid", "orchids", "orchidaceae",
})

# Positive acceptance pattern for Latin botanical epithets.
# Endings like -ur and -or admit too much ordinary English and are intentionally excluded.
_VALID_EPITHET_RE = re.compile(
    r"(?:a|ae|is|us|um|eps|ens|ans|alis|ensis|oides|ia|ii|ina|inum|inae|ica|ula|ella|ellum"
    r"|flora|folia|folius|folium)$"
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


def _extract_genera_from_query(question: str) -> list[str]:
    """Extract scientific genera from binomial name patterns in a question.

    Matches patterns such as ``*Calypso bulbosa*``, ``Calypso bulbosa``, or
    any Title-case word followed by a lowercase species epithet (≥5 chars),
    which is the standard signature of a scientific binomial.  Common English
    stopwords are excluded so sentence-initial words like "How" are not returned.
    """
    pattern = r"\*?([A-Z][a-z]{2,})\s+[a-z]{5,}\*?"
    seen: set[str] = set()
    result: list[str] = []
    for match in re.finditer(pattern, question):
        candidate = match.group(1)
        if candidate.casefold() in _STOPWORDS_LOWER:
            continue
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def _extract_potential_genera(text: str) -> list[str]:
    """Extract Title-case words from *text* that could be botanical genera.

    Excludes common English stopwords and higher-taxon name endings (-aceae, etc.).
    Does NOT require a following epithet — suitable for standalone genus detection.
    """
    seen: set[str] = set()
    result: list[str] = []
    for match in re.finditer(r"\b([A-Z][a-z]{2,})\b", text):
        candidate = match.group(1)
        cf = candidate.casefold()
        if cf in _STOPWORDS_LOWER:
            continue
        if candidate.endswith(("aceae", "idae", "ales", "iformes")):
            continue
        if cf not in seen:
            seen.add(cf)
            result.append(candidate)
    return result


def extract_taxa(text: str, *, resolver: object | None = None) -> list[str]:
    """Extract scientific binomial names from *text* in encounter order.

    Uses a positive-accept pattern for Latin epithets (e.g. ``-a``, ``-ae``,
    ``-is``, ``-eps``). Endings like ``-ur`` and ``-or`` that admit too much
    ordinary English are rejected unless a *resolver* overrides them.

    A *resolver* must expose ``resolve(binomial: str) -> str | None``.  When
    it returns a non-``None`` value the lexical rules are bypassed and the
    canonical form is used instead.

    Bare genera from the curated ``_ORCHID_GENERA`` list are also returned
    when they appear without a following recognised epithet.
    """
    result: list[str] = []
    seen: set[str] = set()
    genus_in_binomial: set[str] = set()

    for match in re.finditer(r"\b([A-Z][a-z]{2,})\s+([a-z]{5,})\b", text):
        genus = match.group(1)
        epithet = match.group(2)

        if genus.casefold() in _STOPWORDS_LOWER:
            continue
        if genus.endswith(("aceae", "idae", "ales", "iformes")):
            continue

        lexical_binomial = f"{genus} {epithet}"

        # Try resolver first — it may accept names the lexical rules reject.
        resolved: str | None = None
        if resolver is not None:
            resolved = resolver.resolve(lexical_binomial)  # type: ignore[union-attr]

        if resolved is None:
            epithet_ok = bool(_VALID_EPITHET_RE.search(epithet))
            if not epithet_ok:
                continue
            binomial = lexical_binomial
        else:
            binomial = resolved

        key = binomial.casefold()
        if key not in seen:
            seen.add(key)
            result.append(binomial)
        genus_in_binomial.add(genus.casefold())

    # Include bare curated genera that are not already part of a found binomial.
    for genus in _ORCHID_GENERA:
        if genus.casefold() in genus_in_binomial:
            continue
        if re.search(rf"\b{re.escape(genus)}\b", text):
            key = genus.casefold()
            if key not in seen:
                seen.add(key)
                result.append(genus)

    return result


def _mentioned_genera(question: str, *, extra_taxa: list[str] | None = None) -> list[str]:
    """Return all orchid genera mentioned in the question.

    Checks the canonical known-genera list by word boundary, then appends
    any additional genera extracted from scientific binomial patterns (e.g.
    ``*Calypso bulbosa*`` → ``Calypso``).  Genera from *extra_taxa* binomials
    are appended last.  The union is returned in encounter order with no
    duplicates.
    """
    normalized = question.casefold()
    known_hits = [
        genus
        for genus in _ORCHID_GENERA
        if re.search(rf"\b{re.escape(genus.casefold())}\b", normalized)
    ]
    seen = {g.casefold() for g in known_hits}
    for g in _extract_genera_from_query(question):
        if g.casefold() not in seen:
            known_hits.append(g)
            seen.add(g.casefold())
    if extra_taxa:
        for taxon in extra_taxa:
            genus = taxon.split()[0]
            if genus.casefold() not in seen:
                known_hits.append(genus)
                seen.add(genus.casefold())
    return known_hits


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
    question: str, *, taxa: list[str] | None = None, max_queries: int = 8
) -> list[str]:
    """Build focused Europe PMC searches from a natural-language Calyx question."""

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

    # Fallback: when explicit taxa are provided, ensure each genus appears in ≥1 query.
    if taxa and len(queries) < max_queries:
        covered = {g for g in ordered_genera if any(g in q for q in queries)}
        for taxon_str in taxa:
            if len(queries) >= max_queries:
                break
            genus = taxon_str.split()[0]
            if genus not in covered:
                queries.append(
                    f'"{genus}" (Orchidaceae OR orchid OR ecology OR mycorrhiza)'
                )
                covered.add(genus)

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


def _relevance_score(record: dict[str, Any], question: str) -> float:
    """Rank records for the actual physiological question, not generic orchid match."""

    question_cf = question.casefold()
    title = str(record.get("title") or "").casefold()
    abstract = str(record.get("abstract") or "").casefold()
    text = title + " " + abstract
    mentioned = _mentioned_genera(question)
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


def search_europe_pmc(query: str, *, limit: int = 8) -> dict[str, Any]:
    """Discover and relevance-rank external literature for a Calyx research turn."""

    timeout = max(
        1.0,
        min(float(os.getenv("CALYX_EXTERNAL_LITERATURE_TIMEOUT_SECONDS", "12")), 30.0),
    )
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
            record["relevance_score"] = _relevance_score(record, query)
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

    all_queries_failed = bool(diagnostics) and len(diagnostics) >= len(query_plan) > 0
    if all_queries_failed:
        availability_state = "UNAVAILABLE"
    elif not results and not candidates:
        availability_state = "EMPTY"
    elif results and len(results) < 2 and len(candidates) > 0:
        availability_state = "INSUFFICIENT_EVIDENCE"
    else:
        availability_state = "AVAILABLE"

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
        "availability_state": availability_state,
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
