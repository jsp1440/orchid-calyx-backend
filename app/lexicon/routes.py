from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from app.concepts.repositories import concept_database_url
from app.scientific_synthesis.language import BotanicalLanguageService
from app.scientific_synthesis.language_routes import _concept_search, _load_concept_service

# Included by app.routers.calyx_core whose parent prefix is /api.
router = APIRouter(prefix="/lexicon", tags=["illustrated-orchid-lexicon"])


def _slug(value: str) -> str:
    value = value.casefold().strip()
    value = re.sub(r"[^a-z0-9×]+", "-", value)
    return value.strip("-")


def _connect():
    return psycopg.connect(concept_database_url(), row_factory=dict_row)


def _definition_map(rows: list[dict[str, Any]]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for row in rows:
        kind = str(row.get("definition_type") or "")
        text = str(row.get("text") or "").strip()
        if text and kind not in mapped:
            mapped[kind] = text
    return mapped


def _entry_payload(
    concept: dict[str, Any],
    labels: list[dict[str, Any]],
    definitions: list[dict[str, Any]],
) -> dict[str, Any]:
    preferred = next(
        (row for row in labels if row.get("label_type") == "PREFERRED"),
        labels[0] if labels else None,
    )
    preferred_term = str((preferred or {}).get("label") or concept["concept_id"])
    alternates = [
        str(row["label"])
        for row in labels
        if row.get("label_type") in {"ALTERNATE", "HISTORICAL", "ABBREVIATION"}
        and row.get("label")
    ]
    defs = _definition_map(definitions)
    quick = defs.get("GLOSSARY") or defs.get("PLAIN_LANGUAGE") or defs.get("LEARNER")
    expanded = defs.get("NORMATIVE_SCIENTIFIC") or defs.get("GLOSSARY")
    maturity: list[str] = []
    if quick or expanded:
        maturity.append("core_definition")
    if concept.get("status") == "ACTIVE":
        maturity.append("scientifically_enriched")
    if concept.get("review_state") == "APPROVED":
        maturity.append("expert_reviewed")

    return {
        "id": str(concept["concept_id"]),
        "concept_id": str(concept["concept_id"]),
        "concept_uri": concept.get("concept_uri"),
        "slug": _slug(preferred_term),
        "preferred_term": preferred_term,
        "quick_definition": quick,
        "expanded_definition": expanded,
        "synonyms": alternates,
        "category": None,
        "subcategory": None,
        "maturity": maturity,
        "review_state": str(concept.get("review_state") or "PENDING").casefold(),
        "certainty_summary": None,
        "source_system": "oc_concepts",
        "source_record_id": str(concept["concept_id"]),
        "date_created": concept.get("created_at"),
        "date_revised": concept.get("revised_at"),
        "provenance": {
            "source": "Orchid Continuum Core Concept Registry",
            "source_record_id": str(concept["concept_id"]),
            "validation_status": str(concept.get("review_state") or "PENDING").casefold(),
        },
        "relationships": [],
        "assets": [],
        "literature": [],
        "character_states": [],
        "example_taxa": [],
        "definition_versions": [
            {
                "version": str(row.get("definition_id")),
                "date": row.get("revised_at") or row.get("created_at"),
                "definition": row.get("text"),
                "summary": str(row.get("definition_type") or "definition"),
                "review_state": str(row.get("review_state") or "PENDING").casefold(),
                "sources": [str((row.get("provenance") or {}).get("citation"))]
                if (row.get("provenance") or {}).get("citation")
                else [],
            }
            for row in definitions
        ],
    }


def _load_entries(*, q: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    try:
        with _connect() as conn, conn.cursor() as cur:
            params: list[Any] = []
            where = ["c.status='ACTIVE'", "c.review_state='APPROVED'"]
            if q:
                needle = f"%{q.casefold().strip()}%"
                where.append(
                    "EXISTS (SELECT 1 FROM oc_concepts.concept_labels sx "
                    "WHERE sx.concept_id=c.concept_id AND sx.normalized_label LIKE %s)"
                )
                params.append(needle)
            params.append(max(1, min(limit, 2000)))
            cur.execute(
                f"""
                SELECT c.*
                FROM oc_concepts.concepts c
                WHERE {' AND '.join(where)}
                ORDER BY c.revised_at DESC, c.created_at DESC, c.concept_id
                LIMIT %s
                """,
                params,
            )
            concepts = [dict(row) for row in cur.fetchall()]
            if not concepts:
                return []
            ids = [row["concept_id"] for row in concepts]
            cur.execute(
                """
                SELECT * FROM oc_concepts.concept_labels
                WHERE concept_id = ANY(%s)
                  AND review_state='APPROVED'
                ORDER BY concept_id,
                  CASE label_type WHEN 'PREFERRED' THEN 0 ELSE 1 END,
                  normalized_label
                """,
                (ids,),
            )
            labels_by: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
            for row in cur.fetchall():
                labels_by[row["concept_id"]].append(dict(row))
            cur.execute(
                """
                SELECT * FROM oc_concepts.concept_definitions
                WHERE concept_id = ANY(%s)
                  AND review_state='APPROVED'
                ORDER BY concept_id, definition_type, revised_at DESC
                """,
                (ids,),
            )
            defs_by: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
            for row in cur.fetchall():
                defs_by[row["concept_id"]].append(dict(row))
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "LEXICON_DATABASE_UNAVAILABLE"},
        ) from exc

    return [
        _entry_payload(concept, labels_by[concept["concept_id"]], defs_by[concept["concept_id"]])
        for concept in concepts
        if labels_by[concept["concept_id"]]
    ]


@router.get("")
def list_entries(
    q: str | None = Query(default=None, max_length=300),
    limit: int = Query(default=500, ge=1, le=2000),
) -> dict[str, Any]:
    entries = _load_entries(q=q, limit=limit)
    return {
        "release": "CALYX-LEXICON-INTEGRATION-001",
        "count": len(entries),
        "entries": entries,
        "source_of_truth": "oc_concepts",
        "automatic_publication": False,
        "visibility": "ACTIVE + APPROVED concepts only",
    }


@router.get("/search")
def search_entries(
    q: str = Query(..., min_length=1, max_length=300),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    entries = _load_entries(q=q, limit=limit)
    return {"query": q, "count": len(entries), "entries": entries}


@router.get("/language/{term}")
def analyze_lexicon_language(term: str) -> dict[str, Any]:
    concept_service = _load_concept_service()
    service = BotanicalLanguageService(
        (lambda value: _concept_search(concept_service, value)) if concept_service else None
    )
    result = service.analyze_term(term)
    result.update(
        {
            "lexicon_release": "CALYX-LEXICON-INTEGRATION-001",
            "canonical_concept_registry": "/api/concepts",
            "botanical_language": "/api/scientific-interpretation/language",
        }
    )
    return result


@router.get("/capabilities")
def lexicon_capabilities() -> dict[str, Any]:
    return {
        "status": "integrated",
        "source_ui": "Famous AI Illustrated Orchid Lexicon",
        "canonical_concept_registry": "/api/concepts",
        "canonical_lexicon_api": "/api/lexicon",
        "botanical_language": "/api/scientific-interpretation/language",
        "vision_lexicon": "/api/vision-lexicon",
        "calyx_conversation": "/api/calyx/speak/conversations",
        "literature_glossary": "/api/literature-extraction",
        "knowledge_graph": "/api/knowledge-graph",
        "governance": {
            "empty_fields_are_legitimate": True,
            "invented_enrichment_prohibited": True,
            "public_entries_require_active_concept": True,
            "public_entries_require_approved_review": True,
            "automatic_concept_promotion": False,
            "automatic_publication": False,
        },
    }
