from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Path, Query
from psycopg.rows import dict_row

from app.concepts.repositories import concept_database_url
from app.scientific_synthesis.language import BotanicalLanguageService
from app.scientific_synthesis.language_routes import _concept_search, _load_concept_service

from .intake_routes import router as intake_router

router = APIRouter(prefix="/lexicon", tags=["illustrated-orchid-lexicon"])
router.include_router(intake_router)


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
                    "(EXISTS (SELECT 1 FROM oc_concepts.concept_labels sx "
                    "WHERE sx.concept_id=c.concept_id AND sx.review_state='APPROVED' "
                    "AND sx.normalized_label LIKE %s) OR "
                    "EXISTS (SELECT 1 FROM oc_concepts.concept_definitions sd "
                    "WHERE sd.concept_id=c.concept_id AND sd.review_state='APPROVED' "
                    "AND lower(sd.text) LIKE %s))"
                )
                params.extend([needle, needle])
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
        raise HTTPException(status_code=503, detail={"code": "LEXICON_DATABASE_UNAVAILABLE"}) from exc

    return [
        _entry_payload(concept, labels_by[concept["concept_id"]], defs_by[concept["concept_id"]])
        for concept in concepts
        if labels_by[concept["concept_id"]]
    ]


def _load_entry_by_concept_id(concept_id: UUID) -> dict[str, Any] | None:
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM oc_concepts.concepts
                WHERE concept_id=%s AND status='ACTIVE' AND review_state='APPROVED'
                """,
                (concept_id,),
            )
            concept_row = cur.fetchone()
            if concept_row is None:
                return None
            concept = dict(concept_row)
            cur.execute(
                """
                SELECT * FROM oc_concepts.concept_labels
                WHERE concept_id=%s AND review_state='APPROVED'
                ORDER BY CASE label_type WHEN 'PREFERRED' THEN 0 ELSE 1 END, normalized_label
                """,
                (concept_id,),
            )
            labels = [dict(row) for row in cur.fetchall()]
            if not labels:
                return None
            cur.execute(
                """
                SELECT * FROM oc_concepts.concept_definitions
                WHERE concept_id=%s AND review_state='APPROVED'
                ORDER BY definition_type, revised_at DESC
                """,
                (concept_id,),
            )
            definitions = [dict(row) for row in cur.fetchall()]
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail={"code": "LEXICON_DATABASE_UNAVAILABLE"}) from exc
    return _entry_payload(concept, labels, definitions)


def _find_approved_concept_id_by_slug(slug: str) -> UUID | None:
    normalized_slug = _slug(slug)
    if not normalized_slug:
        return None
    try:
        with _connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT c.concept_id
                FROM oc_concepts.concepts c
                JOIN oc_concepts.concept_labels l ON l.concept_id=c.concept_id
                WHERE c.status='ACTIVE'
                  AND c.review_state='APPROVED'
                  AND l.review_state='APPROVED'
                  AND btrim(
                    regexp_replace(lower(trim(l.label)), '[^a-z0-9×]+', '-', 'g'),
                    '-'
                  ) = %s
                ORDER BY c.concept_id
                LIMIT 2
                """,
                (normalized_slug,),
            )
            rows = cur.fetchall()
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(status_code=503, detail={"code": "LEXICON_DATABASE_UNAVAILABLE"}) from exc
    if len(rows) > 1:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "LEXICON_APPROVED_SLUG_AMBIGUOUS",
                "message": "More than one ACTIVE + APPROVED concept has this approved normalized label.",
                "slug": normalized_slug,
            },
        )
    return rows[0]["concept_id"] if rows else None


def _load_entry_by_slug(slug: str) -> dict[str, Any] | None:
    concept_id = _find_approved_concept_id_by_slug(slug)
    return _load_entry_by_concept_id(concept_id) if concept_id is not None else None


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


@router.get("/entries/{slug}")
def get_approved_entry_by_slug(
    slug: str = Path(..., min_length=1, max_length=240),
) -> dict[str, Any]:
    entry = _load_entry_by_slug(slug)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "LEXICON_APPROVED_ENTRY_NOT_FOUND",
                "message": "No ACTIVE + APPROVED Lexicon concept is available for this slug.",
            },
        )
    return {
        "release": "CALYX-LEXICON-LIVE-002",
        "entry": entry,
        "source_of_truth": "oc_concepts",
        "automatic_publication": False,
        "visibility": "ACTIVE + APPROVED concepts only",
    }


@router.get("/concepts/{concept_id}")
def get_approved_concept(concept_id: UUID) -> dict[str, Any]:
    entry = _load_entry_by_concept_id(concept_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "LEXICON_APPROVED_CONCEPT_NOT_FOUND",
                "message": "No ACTIVE + APPROVED Lexicon concept is available for this concept_id.",
            },
        )
    return {
        "release": "CALYX-LEXICON-INTEGRATION-001",
        "entry": entry,
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
        "canonical_entry_by_slug": "/api/lexicon/entries/{slug}",
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
            "ambiguous_approved_slugs_fail_closed": True,
            "automatic_concept_promotion": False,
            "automatic_publication": False,
        },
    }
