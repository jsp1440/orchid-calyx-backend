from __future__ import annotations

import re
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query

from app.security import verify_owner_or_api_key

from .service import ResearchTraitsService

GENUS_RE = re.compile(r"^[A-Z][A-Za-z-]{1,79}$")
SPECIES_RE = re.compile(r"^[A-Z][A-Za-z-]{1,79} [a-z][A-Za-z-]{1,79}$")

router = APIRouter(
    prefix="/api/research",
    tags=["research-traits"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


@lru_cache(maxsize=1)
def get_service() -> ResearchTraitsService:
    return ResearchTraitsService()


def _subject(genus: str | None, species: str | None) -> tuple[str, str]:
    supplied = int(bool(genus)) + int(bool(species))
    if supplied != 1:
        raise HTTPException(status_code=422, detail="Supply exactly one of genus or species")
    if genus is not None:
        name = genus.strip()
        if not GENUS_RE.fullmatch(name):
            raise HTTPException(status_code=422, detail="Invalid genus")
        return "genus", name
    name = (species or "").strip()
    if not SPECIES_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="Invalid species binomial")
    return "species", name


@router.get("/traits")
def research_traits(
    genus: str | None = Query(default=None, min_length=2, max_length=80),
    species: str | None = Query(default=None, min_length=3, max_length=161),
):
    rank, name = _subject(genus, species)
    return get_service().get(rank=rank, name=name)
