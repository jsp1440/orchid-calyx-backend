from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.web_collection.models import (
    BrowseResult,
    CollectionEntry,
    CollectionEntryStatus,
    SearchResult,
    TaxonomicRank,
)

router = APIRouter(prefix="/api/collection", tags=["web-collection"])

_STUB_ENTRIES: list[CollectionEntry] = [
    CollectionEntry(
        taxon_id="orch-001",
        taxon_name="Phalaenopsis amabilis",
        common_names=["Moon Orchid", "White Moth Orchid"],
        taxonomic_rank=TaxonomicRank.SPECIES,
        family="Orchidaceae",
        genus="Phalaenopsis",
        status=CollectionEntryStatus.ACTIVE,
        description="A widespread epiphytic orchid native to Southeast Asia.",
        habitat_notes="Grows in humid lowland forests.",
        distribution_notes="Indonesia, Philippines, Papua New Guinea, Australia.",
        image_count=12,
    ),
    CollectionEntry(
        taxon_id="orch-002",
        taxon_name="Cattleya labiata",
        common_names=["Crimson Cattleya", "Autumn Cattleya"],
        taxonomic_rank=TaxonomicRank.SPECIES,
        family="Orchidaceae",
        genus="Cattleya",
        status=CollectionEntryStatus.ACTIVE,
        description="The first Cattleya species introduced to cultivation in Europe.",
        habitat_notes="Epiphytic on trees in Atlantic Forest remnants.",
        distribution_notes="Endemic to northeastern Brazil.",
        image_count=8,
    ),
    CollectionEntry(
        taxon_id="orch-003",
        taxon_name="Vanilla planifolia",
        common_names=["Flat-leaved Vanilla", "Vanilla Orchid"],
        taxonomic_rank=TaxonomicRank.SPECIES,
        family="Orchidaceae",
        genus="Vanilla",
        status=CollectionEntryStatus.ACTIVE,
        description="The primary commercial source of natural vanilla flavoring.",
        habitat_notes="Climbing vine in tropical forests.",
        distribution_notes="Mexico and Central America; widely cultivated globally.",
        image_count=5,
    ),
    CollectionEntry(
        taxon_id="orch-004",
        taxon_name="Dendrobium nobile",
        common_names=["Noble Dendrobium"],
        taxonomic_rank=TaxonomicRank.SPECIES,
        family="Orchidaceae",
        genus="Dendrobium",
        status=CollectionEntryStatus.ACTIVE,
        description="A popular ornamental orchid with fragrant flowers.",
        habitat_notes="Epiphytic in montane forests, 200–1500 m elevation.",
        distribution_notes="India, Nepal, southern China, Southeast Asia.",
        image_count=10,
    ),
    CollectionEntry(
        taxon_id="orch-005",
        taxon_name="Dracula vampira",
        common_names=["Vampire Orchid", "Dracula Orchid"],
        taxonomic_rank=TaxonomicRank.SPECIES,
        family="Orchidaceae",
        genus="Dracula",
        status=CollectionEntryStatus.ACTIVE,
        description="Named for the dark, dramatic appearance of its flower.",
        habitat_notes="Cool, very humid cloud forest.",
        distribution_notes="Ecuador and Colombia.",
        image_count=3,
    ),
]

_ENTRY_INDEX: dict[str, CollectionEntry] = {e.taxon_id: e for e in _STUB_ENTRIES}


def _matches_search(entry: CollectionEntry, q: str) -> bool:
    if not q:
        return True
    q_lower = q.lower()
    fields = [
        entry.taxon_name,
        entry.family or "",
        entry.genus or "",
        *entry.common_names,
    ]
    return any(q_lower in f.lower() for f in fields)


@router.get("/search", response_model=SearchResult)
def search_collection(
    q: Annotated[str, Query(description="Search query")] = "",
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SearchResult:
    matched = [e for e in _STUB_ENTRIES if _matches_search(e, q)]
    page = matched[offset : offset + limit]
    return SearchResult(
        query=q,
        entries=page,
        total=len(matched),
        offset=offset,
        limit=limit,
    )


@router.get("/browse", response_model=BrowseResult)
def browse_collection(
    family: Annotated[str | None, Query(description="Filter by family")] = None,
    genus: Annotated[str | None, Query(description="Filter by genus")] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BrowseResult:
    filtered = _STUB_ENTRIES
    if family is not None:
        filtered = [e for e in filtered if e.family and e.family.lower() == family.lower()]
    if genus is not None:
        filtered = [e for e in filtered if e.genus and e.genus.lower() == genus.lower()]
    page = filtered[offset : offset + limit]
    return BrowseResult(
        family=family,
        genus=genus,
        entries=page,
        total=len(filtered),
        offset=offset,
        limit=limit,
    )


@router.get("/species/{taxon_id}", response_model=CollectionEntry)
def get_species(taxon_id: str) -> CollectionEntry:
    entry = _ENTRY_INDEX.get(taxon_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Taxon '{taxon_id}' not found.")
    return entry
