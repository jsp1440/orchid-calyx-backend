from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.web_collection.models import BrowseResult, CollectionEntry, SearchResult
from app.web_collection.service import (
    CollectionRepository,
    PostgresCollectionRepository,
)

router = APIRouter(prefix="/api/collection", tags=["web-collection"])


def get_collection_repository() -> CollectionRepository:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise HTTPException(
            status_code=503,
            detail="Canonical orchid collection database is not configured.",
        )
    return PostgresCollectionRepository(dsn)


def _service_unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail="Canonical orchid collection is unavailable.",
    )


@router.get("/search", response_model=SearchResult)
def search_collection(
    repository: Annotated[CollectionRepository, Depends(get_collection_repository)],
    q: Annotated[str, Query(description="Scientific name or genus query", max_length=200)] = "",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchResult:
    query = " ".join(q.split())
    try:
        entries, total = repository.search(query, offset=offset, limit=limit)
    except Exception as exc:
        raise _service_unavailable() from exc
    return SearchResult(
        query=query,
        entries=entries,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/browse", response_model=BrowseResult)
def browse_collection(
    repository: Annotated[CollectionRepository, Depends(get_collection_repository)],
    family: Annotated[str | None, Query(description="Filter by family", max_length=100)] = None,
    genus: Annotated[str | None, Query(description="Filter by genus", max_length=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BrowseResult:
    normalized_family = " ".join(family.split()) if family else None
    normalized_genus = " ".join(genus.split()) if genus else None
    try:
        entries, total = repository.browse(
            family=normalized_family,
            genus=normalized_genus,
            offset=offset,
            limit=limit,
        )
    except Exception as exc:
        raise _service_unavailable() from exc
    return BrowseResult(
        family=normalized_family,
        genus=normalized_genus,
        entries=entries,
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/species/{taxon_id}", response_model=CollectionEntry)
def get_species(
    taxon_id: str,
    repository: Annotated[CollectionRepository, Depends(get_collection_repository)],
) -> CollectionEntry:
    try:
        entry = repository.get(taxon_id.strip())
    except Exception as exc:
        raise _service_unavailable() from exc
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Taxon '{taxon_id}' not found.")
    return entry
