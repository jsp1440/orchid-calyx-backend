from __future__ import annotations

import re
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.concepts.repositories import concept_database_url

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z-]{2,}")


def _connect():
    return psycopg.connect(concept_database_url(), row_factory=dict_row)


def candidate_phrases(text: str, *, max_words: int = 4, max_phrases: int = 96) -> list[str]:
    """Return bounded normalized n-grams that may resolve to approved concepts."""
    words = [match.group(0).casefold() for match in _TOKEN_RE.finditer(text)]
    phrases: list[str] = []
    seen: set[str] = set()
    for width in range(min(max_words, len(words)), 0, -1):
        for start in range(0, len(words) - width + 1):
            phrase = " ".join(words[start : start + width])
            if phrase in seen:
                continue
            seen.add(phrase)
            phrases.append(phrase)
            if len(phrases) >= max_phrases:
                return phrases
    return phrases


def build_semantic_context(text: str, *, limit: int = 12) -> dict[str, Any]:
    """Resolve text against ACTIVE + APPROVED Orchid Continuum concepts.

    This is a read-only projection for Calyx conversation. It does not create,
    promote, revise, or publish concepts.
    """
    candidates = candidate_phrases(text)
    if not candidates:
        return {
            "status": "available",
            "links": [],
            "source_of_truth": "oc_concepts",
            "read_only": True,
            "automatic_publication": False,
        }

    resolved_limit = max(1, min(int(limit), 30))
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.concept_id,
                    c.concept_uri,
                    l.label,
                    l.normalized_label,
                    l.label_type
                FROM oc_concepts.concept_labels l
                JOIN oc_concepts.concepts c ON c.concept_id = l.concept_id
                WHERE c.status='ACTIVE'
                  AND c.review_state='APPROVED'
                  AND l.review_state='APPROVED'
                  AND l.normalized_label = ANY(%s)
                ORDER BY
                    CASE l.label_type WHEN 'PREFERRED' THEN 0 ELSE 1 END,
                    length(l.normalized_label) DESC,
                    l.normalized_label,
                    c.concept_id
                LIMIT %s
                """,
                (candidates, resolved_limit * 4),
            )
            rows = [dict(row) for row in cur.fetchall()]
            if not rows:
                return {
                    "status": "available",
                    "links": [],
                    "source_of_truth": "oc_concepts",
                    "read_only": True,
                    "automatic_publication": False,
                }

            concept_ids = list(dict.fromkeys(row["concept_id"] for row in rows))
            cur.execute(
                """
                SELECT concept_id, definition_type, text
                FROM oc_concepts.concept_definitions
                WHERE concept_id = ANY(%s)
                  AND review_state='APPROVED'
                ORDER BY concept_id,
                    CASE definition_type
                        WHEN 'GLOSSARY' THEN 0
                        WHEN 'PLAIN_LANGUAGE' THEN 1
                        WHEN 'LEARNER' THEN 2
                        WHEN 'NORMATIVE_SCIENTIFIC' THEN 3
                        ELSE 4
                    END,
                    revised_at DESC
                """,
                (concept_ids,),
            )
            definitions: dict[Any, str] = {}
            for row in cur.fetchall():
                if row["concept_id"] not in definitions and row.get("text"):
                    definitions[row["concept_id"]] = str(row["text"]).strip()
    except (RuntimeError, psycopg.Error) as exc:
        return {
            "status": "unavailable",
            "links": [],
            "source_of_truth": "oc_concepts",
            "read_only": True,
            "automatic_publication": False,
            "diagnostics": [{"source": "semantic_context", "error": str(exc)}],
        }

    preferred_by_concept: dict[Any, dict[str, Any]] = {}
    match_by_concept: dict[Any, str] = {}
    for row in rows:
        concept_id = row["concept_id"]
        match_by_concept.setdefault(concept_id, str(row["normalized_label"]))
        if concept_id not in preferred_by_concept or row.get("label_type") == "PREFERRED":
            preferred_by_concept[concept_id] = row

    links: list[dict[str, Any]] = []
    for concept_id, row in preferred_by_concept.items():
        links.append(
            {
                "concept_id": str(concept_id),
                "concept_uri": row.get("concept_uri"),
                "term": str(row.get("label") or match_by_concept[concept_id]),
                "matched_normalized_label": match_by_concept[concept_id],
                "definition": definitions.get(concept_id),
                "href": f"/api/lexicon/concepts/{concept_id}",
                "source_of_truth": "oc_concepts",
                "review_state": "approved",
            }
        )
        if len(links) >= resolved_limit:
            break

    return {
        "status": "available",
        "links": links,
        "source_of_truth": "oc_concepts",
        "read_only": True,
        "automatic_publication": False,
    }
