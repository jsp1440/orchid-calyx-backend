from __future__ import annotations

from collections.abc import Sequence

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.web_collection.models import (
    CollectionEntry,
    CollectionEntryProvenance,
    CollectionEntryStatus,
    TaxonomicRank,
)
from app.web_collection.routes import get_collection_repository, router


def entry(taxon_id: str, name: str, genus: str, image_count: int = 0) -> CollectionEntry:
    return CollectionEntry(
        taxon_id=taxon_id,
        taxon_name=name,
        common_names=[],
        taxonomic_rank=TaxonomicRank.SPECIES,
        family="Orchidaceae",
        genus=genus,
        status=CollectionEntryStatus.CANONICAL_RECORD,
        image_count=image_count,
        provenance=CollectionEntryProvenance(
            source_table="public.orchid_taxonomy",
            source_record_id=taxon_id,
            identity_state="canonical_table_record",
        ),
    )


ENTRIES = [
    entry("1", "Cattleya labiata", "Cattleya", 8),
    entry("2", "Phalaenopsis amabilis", "Phalaenopsis", 12),
    entry("3", "Phalaenopsis aphrodite", "Phalaenopsis", 4),
]


class StubRepository:
    def search(self, query: str, *, offset: int, limit: int) -> tuple[list[CollectionEntry], int]:
        normalized = query.casefold()
        matches = [
            item
            for item in ENTRIES
            if normalized in item.taxon_name.casefold() or normalized in (item.genus or "").casefold()
        ]
        return matches[offset : offset + limit], len(matches)

    def browse(
        self,
        *,
        family: str | None,
        genus: str | None,
        offset: int,
        limit: int,
    ) -> tuple[list[CollectionEntry], int]:
        matches: Sequence[CollectionEntry] = ENTRIES
        if family and family.casefold() != "orchidaceae":
            matches = []
        if genus:
            matches = [item for item in matches if (item.genus or "").casefold() == genus.casefold()]
        return list(matches[offset : offset + limit]), len(matches)

    def get(self, taxon_id: str) -> CollectionEntry | None:
        return next((item for item in ENTRIES if item.taxon_id == taxon_id), None)


def make_client(repository: StubRepository | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    if repository is not None:
        app.dependency_overrides[get_collection_repository] = lambda: repository
    return TestClient(app)


def test_search_returns_canonical_taxa_with_provenance() -> None:
    response = make_client(StubRepository()).get(
        "/api/collection/search",
        params={"q": "  phalaenopsis  ", "limit": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "phalaenopsis"
    assert data["total"] == 2
    assert len(data["entries"]) == 1
    assert data["entries"][0]["taxon_id"] == "2"
    assert data["entries"][0]["provenance"] == {
        "source_table": "public.orchid_taxonomy",
        "source_record_id": "2",
        "identity_state": "canonical_table_record",
    }


def test_browse_filters_by_genus_case_insensitively() -> None:
    response = make_client(StubRepository()).get(
        "/api/collection/browse",
        params={"family": "Orchidaceae", "genus": "phalaenopsis"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert {item["taxon_name"] for item in data["entries"]} == {
        "Phalaenopsis amabilis",
        "Phalaenopsis aphrodite",
    }


def test_browse_non_orchid_family_is_empty_not_fabricated() -> None:
    response = make_client(StubRepository()).get(
        "/api/collection/browse",
        params={"family": "Rosaceae"},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 0
    assert response.json()["entries"] == []


def test_get_species_preserves_canonical_identifier_and_real_image_count() -> None:
    response = make_client(StubRepository()).get("/api/collection/species/2")
    assert response.status_code == 200
    data = response.json()
    assert data["taxon_id"] == "2"
    assert data["taxon_name"] == "Phalaenopsis amabilis"
    assert data["image_count"] == 12
    assert data["status"] == "CANONICAL_RECORD"


def test_get_species_not_found() -> None:
    response = make_client(StubRepository()).get("/api/collection/species/unknown")
    assert response.status_code == 404


def test_database_configuration_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = make_client().get("/api/collection/search")
    assert response.status_code == 503
    assert response.json()["detail"] == "Canonical orchid collection database is not configured."


def test_query_bounds_are_enforced() -> None:
    client = make_client(StubRepository())
    assert client.get("/api/collection/search", params={"limit": 0}).status_code == 422
    assert client.get("/api/collection/search", params={"limit": 101}).status_code == 422
    assert client.get("/api/collection/search", params={"offset": -1}).status_code == 422


def test_router_is_mounted_in_production_application() -> None:
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/api/collection/search" in paths
    assert "/api/collection/browse" in paths
    assert "/api/collection/species/{taxon_id}" in paths
