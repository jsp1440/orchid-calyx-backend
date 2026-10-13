"""Read-only TraitBank API (``/api/traitbank``).

GET only. There is no write route: ingestion is the controlled CLI path
(``python -m app.traitbank.cli``). The router uses the same default-deny
dependency as ``/api/research/traits``. No route opts into member reads:
responses carry source excerpts, citations and relation statements that can
name a protected locality in prose, which the ingestion regex guards cannot
detect. Member access needs a fail-closed member projection first (as in
``app/research_traits/routes.py``); until then these routes are owner-only.
"""

from __future__ import annotations

import re
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query

from app.member_auth import owner_or_member_read

from .models import CANONICAL_TAXON_ID_RE, TRAIT_ID_RE
from .service import TraitBankService

GENUS_RE = re.compile(r"^[A-Z][A-Za-z-]{1,79}$")
SPECIES_RE = re.compile(r"^[A-Z][A-Za-z-]{1,79} [a-z][A-Za-z-]{1,79}$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9:._#/@+-]{1,300}$")
HABITAT_RE = re.compile(r"^[A-Za-z][A-Za-z ,'-]{1,119}$")

router = APIRouter(
    prefix="/api/traitbank",
    tags=["traitbank"],
    dependencies=[Depends(owner_or_member_read)],
)


@lru_cache(maxsize=1)
def get_service() -> TraitBankService:
    return TraitBankService()


def _taxon_id(value: str) -> str:
    if not CANONICAL_TAXON_ID_RE.fullmatch(value):
        raise HTTPException(
            status_code=422, detail="taxon_id must be a canonical taxonomy id"
        )
    return value


def _trait_id(value: str) -> str:
    if not TRAIT_ID_RE.fullmatch(value):
        raise HTTPException(status_code=422, detail="Invalid trait_id")
    return value


def _safe_id(value: str, name: str) -> str:
    if not SAFE_ID_RE.fullmatch(value):
        raise HTTPException(status_code=422, detail=f"Invalid {name}")
    return value


@router.get("/taxa/{taxon_id}")
def taxon_traits(taxon_id: str):
    return get_service().taxon(_taxon_id(taxon_id))


@router.get("/species")
def species_traits(name: str = Query(min_length=3, max_length=161)):
    name = name.strip()
    if not SPECIES_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="Invalid species binomial")
    return get_service().species(name)


@router.get("/genera/{genus}")
def genus_traits(genus: str):
    if not GENUS_RE.fullmatch(genus):
        raise HTTPException(status_code=422, detail="Invalid genus")
    return get_service().genus(genus)


@router.get("/characters/{trait_id}")
def character(trait_id: str, taxon_id: str | None = Query(default=None, max_length=19)):
    return get_service().character(
        _trait_id(trait_id), _taxon_id(taxon_id) if taxon_id else None
    )


@router.get("/assertions/{assertion_id:path}")
def assertion(assertion_id: str):
    return get_service().assertion(_safe_id(assertion_id, "assertion_id"))


@router.get("/sources/{source_id:path}")
def source(source_id: str):
    return get_service().source(_safe_id(source_id, "source_id"))


@router.get("/habitats")
def habitat(term: str = Query(min_length=2, max_length=120)):
    if not HABITAT_RE.fullmatch(term.strip()):
        raise HTTPException(status_code=422, detail="Invalid habitat term")
    return get_service().habitat(term.strip())


@router.get("/conflicts")
def conflicts(
    taxon_id: str | None = Query(default=None, max_length=19),
    trait_id: str | None = Query(default=None, max_length=100),
):
    if not taxon_id and not trait_id:
        raise HTTPException(status_code=422, detail="Supply taxon_id or trait_id")
    return get_service().conflicts(
        taxon_id=_taxon_id(taxon_id) if taxon_id else None,
        trait_id=_trait_id(trait_id) if trait_id else None,
    )


@router.get("/taxa/{taxon_id}/calyx/{trait_id}")
def calyx(taxon_id: str, trait_id: str):
    return get_service().calyx(_taxon_id(taxon_id), _trait_id(trait_id))


@router.get("/matrix")
def matrix(
    taxon_id: list[str] = Query(min_length=1, max_length=50),  # noqa: B008 - FastAPI query declaration
    trait_id: str | None = Query(default=None, max_length=100),
):
    return get_service().matrix(
        [_taxon_id(t) for t in taxon_id], _trait_id(trait_id) if trait_id else None
    )
