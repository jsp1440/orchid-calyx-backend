from __future__ import annotations

import re
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.member_auth import member_readable, owner_or_member_read

from .service import ResearchTraitsService

GENUS_RE = re.compile(r"^[A-Z][A-Za-z-]{1,79}$")
SPECIES_RE = re.compile(r"^[A-Z][A-Za-z-]{1,79} [a-z][A-Za-z-]{1,79}$")

router = APIRouter(
    prefix="/api/research",
    tags=["research-traits"],
    dependencies=[Depends(owner_or_member_read)],
)


@lru_cache(maxsize=1)
def get_service() -> ResearchTraitsService:
    return ResearchTraitsService()


def _subject(genus: str | None, species: str | None) -> tuple[str, str]:
    supplied = int(bool(genus)) + int(bool(species))
    if supplied != 1:
        raise HTTPException(
            status_code=422, detail="Supply exactly one of genus or species"
        )
    if genus is not None:
        name = genus.strip()
        if not GENUS_RE.fullmatch(name):
            raise HTTPException(status_code=422, detail="Invalid genus")
        return "genus", name
    name = (species or "").strip()
    if not SPECIES_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail="Invalid species binomial")
    return "species", name


def _member_safe_response(
    request: Request, payload: dict[str, object]
) -> dict[str, object]:
    """Fail closed for member reads until traits have a bounded public vocabulary.

    Canonical trait rows contain source-controlled free-form labels, values, and
    receipts.  Those strings can encode protected locality even when their field
    names are innocuous, so a generic key-based redactor cannot make them safe.
    Owners keep the complete response.  Members receive the same fixed response
    schema and requested taxon identity, with the scientific payload explicitly
    marked WITHHELD rather than silently presented as absent.
    """
    principal = getattr(request.state, "oc_principal", None)
    if not isinstance(principal, dict) or principal.get("role") != "member":
        return payload
    return {
        "contract_version": payload.get("contract_version"),
        "subject": payload.get("subject"),
        "state": "WITHHELD",
        "generated_at": payload.get("generated_at"),
        "distributions": [],
    }


@router.get("/traits")
@member_readable
def research_traits(
    request: Request,
    genus: str | None = Query(default=None, min_length=2, max_length=80),
    species: str | None = Query(default=None, min_length=3, max_length=161),
):
    rank, name = _subject(genus, species)
    payload = get_service().get(rank=rank, name=name)
    return _member_safe_response(request, payload)
