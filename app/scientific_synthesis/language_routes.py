from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.concepts.dependencies import get_concept_service
from app.concepts.services import ConceptRegistryService
from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.routes import get_literature_repository

from .language import (
    BOTANICAL_LATIN_BACKGROUND,
    BotanicalLanguageService,
    word_element_dictionary,
)

router = APIRouter(prefix="/language", tags=["scientific-language"])


class TermAnalysisIn(BaseModel):
    term: str = Field(min_length=1, max_length=300)
    include_concepts: bool = True


def _concept_search(service: ConceptRegistryService, term: str) -> dict[str, Any]:
    try:
        return service.search_concepts(term, limit=10)
    except Exception as exc:
        return {
            "query": term,
            "resolution": "UNAVAILABLE",
            "matches": [],
            "error": type(exc).__name__,
        }


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
        "governance": "lexical reference only; no automatic scientific or nomenclatural assertion",
    }


@router.post("/analyze")
def analyze_term(
    payload: TermAnalysisIn,
    concepts: Annotated[ConceptRegistryService, Depends(get_concept_service)],
):
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
    concepts: Annotated[ConceptRegistryService, Depends(get_concept_service)],
):
    paper = repository.get(paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Literature extraction result not found")
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


@router.get("/health")
def health():
    return {
        "status": "ok",
        "literature_glossary_connected": True,
        "canonical_concept_registry_connected": True,
        "word_roots_and_combining_forms": True,
        "botanical_latin_background": True,
        "automatic_concept_promotion": False,
    }
