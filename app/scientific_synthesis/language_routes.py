from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.concepts.dependencies import get_concept_service
from app.concepts.services import ConceptRegistryService
from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.routes import get_literature_repository

from .glossary_candidates import (
    CandidateConflictError,
    CandidatePersistenceError,
    CandidateState,
    GlossaryCandidateRecord,
    JsonGlossaryCandidateRepository,
)
from .glossary_projection import (
    GlossaryProjectionNotReviewedError,
    project_canonical_glossary_entry,
)
from .language import (
    BOTANICAL_LATIN_BACKGROUND,
    BotanicalLanguageService,
    word_element_dictionary,
)

router = APIRouter(prefix="/language", tags=["scientific-language"])


class TermAnalysisIn(BaseModel):
    term: str = Field(min_length=1, max_length=300)
    include_concepts: bool = True


def get_glossary_candidate_repository() -> JsonGlossaryCandidateRepository:
    root = Path(
        os.getenv(
            "SCIENTIFIC_LANGUAGE_CANDIDATE_ROOT",
            "runtime/scientific_language/candidates",
        )
    )
    return JsonGlossaryCandidateRepository(root)


GlossaryCandidates = Annotated[
    JsonGlossaryCandidateRepository,
    Depends(get_glossary_candidate_repository),
]


def _unavailable(term: str, exc: BaseException | None = None) -> dict[str, Any]:
    return {
        "query": term,
        "resolution": "UNAVAILABLE",
        "matches": [],
        "error": type(exc).__name__ if exc is not None else "ConceptRegistryUnavailable",
    }


def _load_concept_service() -> ConceptRegistryService | None:
    try:
        return get_concept_service()
    except (LookupError, RuntimeError, ValueError, psycopg.Error):
        return None


def _concept_search(
    service: ConceptRegistryService | None,
    term: str,
) -> dict[str, Any]:
    if service is None:
        return _unavailable(term)
    try:
        return service.search_concepts(term, limit=10)
    except (LookupError, RuntimeError, ValueError, psycopg.Error) as exc:
        return _unavailable(term, exc)


@router.get("/botanical-latin")
def botanical_latin_background():
    return BOTANICAL_LATIN_BACKGROUND


@router.get("/word-elements")
def list_word_elements(
    q: str | None = Query(default=None, max_length=120),
):
    items = word_element_dictionary()
    if q:
        needle = q.casefold().strip()
        items = [
            item
            for item in items
            if needle in item["form"].casefold()
            or needle in item["meaning"].casefold()
            or any(needle in value.casefold() for value in item["botanical_examples"])
        ]
    return {
        "release": "OC-BOTANICAL-LANGUAGE-001",
        "count": len(items),
        "items": items,
        "governance": (
            "lexical reference only; no automatic scientific or nomenclatural assertion"
        ),
    }


@router.post("/analyze")
def analyze_term(payload: TermAnalysisIn):
    concepts = _load_concept_service() if payload.include_concepts else None
    search = (
        (lambda term: _concept_search(concepts, term))
        if payload.include_concepts
        else None
    )
    return BotanicalLanguageService(search).analyze_term(payload.term)


@router.get("/papers/{paper_id}")
def analyze_paper_glossary(
    paper_id: str,
    repository: Annotated[
        LiteratureResultRepository, Depends(get_literature_repository)
    ],
):
    paper = repository.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Literature extraction result not found")
    concepts = _load_concept_service()
    service = BotanicalLanguageService(lambda term: _concept_search(concepts, term))
    result = service.analyze_glossary(paper.glossary_terms)
    result.update(
        {
            "paper_id": paper.paper_id,
            "source_hash": paper.source.content_hash,
            "glossary_source": "literature_extraction.glossary_terms",
            "canonical_registry": "/api/concepts",
        }
    )
    return result


def _candidate_storage_error(operation):
    try:
        return operation()
    except CandidateConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "GLOSSARY_CANDIDATE_CONFLICT"},
        ) from exc
    except (CandidatePersistenceError, OSError) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "GLOSSARY_CANDIDATE_PERSISTENCE_UNAVAILABLE"},
        ) from exc


@router.post("/papers/{paper_id}/candidates", status_code=201)
def persist_paper_glossary_candidates(
    paper_id: str,
    repository: Annotated[
        LiteratureResultRepository, Depends(get_literature_repository)
    ],
    candidates: GlossaryCandidates,
):
    paper = repository.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Literature extraction result not found")
    concepts = _load_concept_service()
    analyses = BotanicalLanguageService(
        lambda term: _concept_search(concepts, term)
    ).analyze_glossary(paper.glossary_terms)["items"]

    def persist():
        results = [
            candidates.save(
                GlossaryCandidateRecord.from_analysis(
                    paper_id=paper.paper_id,
                    source_hash=paper.source.content_hash,
                    analysis=analysis,
                )
            )
            for analysis in analyses
        ]
        return {
            "paper_id": paper.paper_id,
            "source_hash": paper.source.content_hash,
            "count": len(results),
            "created_count": sum(result.created for result in results),
            "items": [result.candidate for result in results],
            "review_required": True,
            "canonical_promotion_authorized": False,
            "knowledge_graph_publication_authorized": False,
        }

    return _candidate_storage_error(persist)


@router.get("/candidates")
def list_glossary_candidates(
    candidates: GlossaryCandidates,
    state: Annotated[CandidateState | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    def load():
        records = candidates.list()
        if state is not None:
            records = [record for record in records if record.state == state]
        total = len(records)
        return {
            "items": records[offset : offset + limit],
            "count": min(limit, max(0, total - offset)),
            "total": total,
            "review_required": True,
            "canonical_promotion_authorized": False,
            "knowledge_graph_publication_authorized": False,
        }

    return _candidate_storage_error(load)


@router.get("/candidates/{candidate_id}")
def get_glossary_candidate(
    candidate_id: str,
    candidates: GlossaryCandidates,
):
    record = _candidate_storage_error(lambda: candidates.get(candidate_id))
    if record is None:
        raise HTTPException(status_code=404, detail="Glossary candidate not found")
    return record


@router.get("/glossary/{concept_id}")
def get_canonical_glossary_entry(
    concept_id: str,
    service: Annotated[ConceptRegistryService, Depends(get_concept_service)],
    language: Annotated[str | None, Query(min_length=2, max_length=35)] = None,
):
    try:
        return project_canonical_glossary_entry(
            service,
            concept_id,
            language=language,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": str(exc)},
        ) from exc
    except GlossaryProjectionNotReviewedError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": str(exc)},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": str(exc)},
        ) from exc
    except (RuntimeError, psycopg.Error) as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "CONCEPT_DATABASE_UNAVAILABLE"},
        ) from exc


@router.get("/health")
def health():
    return {
        "status": "ok",
        "literature_glossary_connected": True,
        "canonical_concept_registry_connected": True,
        "word_roots_and_combining_forms": True,
        "botanical_latin_background": True,
        "automatic_concept_promotion": False,
        "durable_candidate_intake": True,
        "reviewed_canonical_glossary_projection": True,
    }
