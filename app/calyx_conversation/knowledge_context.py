"""Knowledge context bridge — read-only grounding from Lexicon and Literature.

Retrieves query-relevant botanical terminology from the OC Lexicon and
evidence-attributed claims from locally stored literature, for injection into
Calyx/Kalix conversation context. Neither store is written to; failures in
either source are contained so Calyx continues functioning.

Governance
----------
- canonical_graph_mutated: False throughout
- engineering_dispatch_authorized: False
- provider_calls: 0
- All reads are from ACTIVE+APPROVED Lexicon concepts and accepted/unreviewed
  literature claims only — no speculative data surfaces here.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

_SCHEMA = "oc.calyx-knowledge-context.v1"
_LEXICON_LIMIT = 8
_LITERATURE_LIMIT = 5
_CLAIMS_PER_PAPER = 3


# ── Shared helpers ────────────────────────────────────────────────────────────


_STOPWORDS = frozenset({
    "the", "and", "for", "not", "but", "its", "are", "was", "has", "had",
    "how", "can", "may", "did", "she", "her", "his", "him", "our", "out",
    "new", "all", "one", "two", "use", "any", "get", "set", "let", "put",
    "what", "that", "this", "with", "from", "they", "them", "then", "when",
    "than", "such", "more", "also", "into", "over", "some", "just", "been",
    "have", "will", "were", "your", "very", "much", "many", "each", "well",
    "tell", "best", "nice", "good", "high", "low", "big", "why", "who",
    "like", "show", "used", "both", "even", "back", "most", "only",
})


def _query_terms(query: str) -> list[str]:
    """Extract candidate botanical/scientific terms (≥3 chars, non-stopword, unique, ordered)."""
    words = re.findall(r"[A-Za-zÀ-ɏ×][a-zÀ-ɏ×]{2,}", query)
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        low = w.lower()
        if low not in seen and low not in _STOPWORDS:
            seen.add(low)
            out.append(w)
    return out[:12]


def _term_overlap(text: str, terms: list[str]) -> int:
    lower = text.casefold()
    return sum(1 for t in terms if t.casefold() in lower)


# ── Lexicon context ───────────────────────────────────────────────────────────


def _lexicon_entries(
    query: str,
    *,
    limit: int = _LEXICON_LIMIT,
    loader: Callable[..., list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Return up to *limit* Lexicon entries relevant to *query*.

    *loader* is injectable for testing; production uses the stable public
    Lexicon search interface.
    """
    if loader is None:
        from app.lexicon.routes import search_concepts as loader

    terms = _query_terms(query)
    if not terms:
        return []

    keyword = " ".join(terms[:3])
    try:
        candidates: list[dict[str, Any]] = loader(q=keyword, limit=max(limit * 4, 40))
    except Exception:  # noqa: BLE001 — Lexicon DB unavailable; bridge continues
        return []

    def _score(e: dict[str, Any]) -> int:
        text = " ".join(filter(None, [
            e.get("preferred_term"),
            e.get("quick_definition"),
            e.get("expanded_definition"),
            " ".join(e.get("synonyms") or []),
        ]))
        return _term_overlap(text, terms)

    ranked = sorted(candidates, key=_score, reverse=True)
    return [e for e in ranked[:limit] if _score(e) > 0]


def build_lexicon_context(
    query: str,
    *,
    limit: int = _LEXICON_LIMIT,
    loader: Callable[..., list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Build a Lexicon grounding block for *query*.

    Returns a dict suitable for inclusion in Calyx governed_context. On any
    failure returns a dict with available=False rather than raising.
    """
    try:
        entries = _lexicon_entries(query, limit=limit, loader=loader)
    except Exception:  # noqa: BLE001
        entries = []

    terms = [
        {
            "preferred_term": e.get("preferred_term"),
            "quick_definition": e.get("quick_definition"),
            "expanded_definition": e.get("expanded_definition"),
            "synonyms": e.get("synonyms") or [],
            "maturity": e.get("maturity") or [],
            "provenance": e.get("provenance") or {
                "source": "Orchid Continuum Core Concept Registry",
                "validation_status": e.get("review_state", "unknown"),
            },
        }
        for e in entries
    ]
    return {
        "schema": _SCHEMA,
        "source": "oc_lexicon",
        "query": query[:200],
        "matched_terms": len(terms),
        "terms": terms,
        "read_only": True,
        "canonical_graph_mutated": False,
        "available": bool(entries),
    }


# ── Literature context ────────────────────────────────────────────────────────

def _score_paper(paper: Any, terms: list[str]) -> int:
    meta = getattr(paper, "metadata", None)
    if meta is None:
        return 0
    text = " ".join(filter(None, [
        getattr(meta, "title", None),
        getattr(meta, "abstract", None),
        " ".join(getattr(meta, "keywords", []) or []),
    ]))
    return _term_overlap(text, terms)


def _accepted_claims(paper: Any, terms: list[str], limit: int) -> list[dict[str, Any]]:
    claims = getattr(paper, "claims", []) or []
    eligible = [
        c for c in claims
        if getattr(getattr(c, "provenance", None), "review_status", "unreviewed")
        in {"accepted", "unreviewed"}
    ]
    scored = sorted(
        eligible,
        key=lambda c: _term_overlap(getattr(c, "statement", ""), terms),
        reverse=True,
    )
    return [
        {
            "claim_id": c.claim_id,
            "statement": c.statement,
            "claim_type": c.claim_type,
            "polarity": c.polarity,
            "provenance": {
                "method": c.provenance.method,
                "confidence": c.provenance.confidence,
                "review_status": c.provenance.review_status,
                "extractor": c.provenance.extractor,
            },
        }
        for c in scored[:limit]
    ]


def _paper_citation(paper: Any) -> dict[str, Any]:
    meta = getattr(paper, "metadata", None) or {}
    if isinstance(meta, dict):
        identifiers: dict[str, str] = {}
        return {
            "paper_id": getattr(paper, "paper_id", None),
            "title": meta.get("title"),
            "authors": meta.get("authors") or [],
            "journal": meta.get("journal"),
            "publication_year": meta.get("publication_year"),
            "doi": None,
            "pmid": None,
        }
    identifiers = {id_.scheme: id_.value for id_ in (getattr(meta, "identifiers", []) or [])}
    manifest = getattr(paper, "analysis_manifest", None)
    return {
        "paper_id": getattr(paper, "paper_id", None),
        "title": getattr(meta, "title", None),
        "authors": getattr(meta, "authors", []) or [],
        "journal": getattr(meta, "journal", None),
        "publication_year": getattr(meta, "publication_year", None),
        "doi": identifiers.get("doi"),
        "pmid": identifiers.get("pmid"),
        "review_status": getattr(manifest, "status", "unknown") if manifest else "unknown",
    }


def build_literature_context(
    query: str,
    *,
    root: str | Path | None = None,
    paper_limit: int = _LITERATURE_LIMIT,
    claims_per_paper: int = _CLAIMS_PER_PAPER,
    repository: Any = None,
) -> dict[str, Any]:
    """Build a Literature grounding block for *query*.

    *repository* is injectable for testing (must implement .get(paper_id)).
    *root* overrides LITERATURE_EXTRACTION_ROOT env var.
    Returns a dict with available=False when no ingested literature is found.
    """
    from app.literature_extraction.repository import LiteratureResultRepository

    if repository is None:
        lit_root: str | Path = root or os.getenv(
            "LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction"
        )
        repository = LiteratureResultRepository(lit_root)

    terms = _query_terms(query)
    try:
        paper_ids = repository.list_paper_ids()
    except Exception:  # noqa: BLE001 — repository unavailable; bridge continues
        paper_ids = []

    if not paper_ids:
        return {
            "schema": _SCHEMA,
            "source": "oc_literature_extraction",
            "query": query[:200],
            "matched_papers": 0,
            "papers": [],
            "read_only": True,
            "canonical_graph_mutated": False,
            "available": False,
            "note": "No ingested literature found in repository.",
        }

    scored: list[tuple[int, Any]] = []
    for pid in paper_ids:
        try:
            paper = repository.get(pid)
        except Exception:  # noqa: BLE001, S112
            continue
        if paper is None:
            continue
        score = _score_paper(paper, terms) if terms else 0
        scored.append((score, paper))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [p for _, p in scored[:paper_limit]]

    papers_out = [
        {
            "citation": _paper_citation(paper),
            "claims": _accepted_claims(paper, terms, claims_per_paper),
            "entities_count": len(getattr(paper, "entities", []) or []),
        }
        for paper in top
    ]

    return {
        "schema": _SCHEMA,
        "source": "oc_literature_extraction",
        "query": query[:200],
        "matched_papers": len(papers_out),
        "papers": papers_out,
        "read_only": True,
        "canonical_graph_mutated": False,
        "available": True,
    }


# ── Combined bridge ───────────────────────────────────────────────────────────


def build_knowledge_context(
    query: str,
    *,
    include_lexicon: bool = True,
    include_literature: bool = True,
    lexicon_loader: Callable[..., list[dict[str, Any]]] | None = None,
    literature_repository: Any = None,
) -> dict[str, Any]:
    """Build combined Lexicon + Literature grounding context for *query*.

    Either source failing independently never propagates to the other or to
    Calyx. The combined result is always safe to include in governed_context.
    """
    lexicon: dict[str, Any] = {
        "schema": _SCHEMA, "source": "oc_lexicon",
        "available": False, "canonical_graph_mutated": False, "read_only": True,
    }
    literature: dict[str, Any] = {
        "schema": _SCHEMA, "source": "oc_literature_extraction",
        "available": False, "canonical_graph_mutated": False, "read_only": True,
    }

    if include_lexicon:
        try:
            lexicon = build_lexicon_context(query, loader=lexicon_loader)
        except Exception:  # noqa: BLE001
            lexicon["error"] = "Lexicon context unavailable."

    if include_literature:
        try:
            literature = build_literature_context(query, repository=literature_repository)
        except Exception:  # noqa: BLE001
            literature["error"] = "Literature context unavailable."

    return {
        "schema": _SCHEMA,
        "query": query[:200],
        "lexicon": lexicon,
        "literature": literature,
        "read_only": True,
        "canonical_graph_mutated": False,
        "engineering_dispatch_authorized": False,
        "provider_calls": 0,
    }
