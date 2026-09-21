"""Journey 2 — species dossier served from Calyx's own tables, honest about every gap, locality-free."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.species_dossier import routes as dossier_routes
from app.species_dossier.repository import (
    PostgresSpeciesRepository,
    split_scientific_name,
)
from app.species_dossier.routes import get_service, router
from app.species_dossier.service import SpeciesDossierService

TAXA = [
    {
        "id": 101,
        "scientific_name": "Phalaenopsis amabilis (L.) Blume",
        "genus": "Phalaenopsis",
    },
    {
        "id": 102,
        "scientific_name": "Phalaenopsis aphrodite Rchb.f.",
        "genus": "Phalaenopsis",
    },
    {"id": 103, "scientific_name": "Dracula vampira (Luer) Luer", "genus": "Dracula"},
]
IMAGES = {
    101: [
        {
            "id": 9001,
            "image_url": "https://images.example/1.jpg",
            "image_source": "iNaturalist",
            "image_license": "CC-BY-NC-4.0",
            "image_rights_holder": "A. Grower",
            "observer_name": "A. Grower",
            "gbif_occurrence_key": "gbif-1",
        },
        {
            "id": 9002,
            "image_url": "https://images.example/2.jpg",
            "image_source": "Wikimedia Commons",
            "image_license": "CC-BY-SA-4.0",
            "image_rights_holder": None,
            "observer_name": "B. Photographer",
            "gbif_occurrence_key": None,
        },
    ]
}
GRAPH_EDGES = {
    101: [
        {
            "edge_type": "pollinated_by",
            "node_type": "pollinator",
            "canonical_key": "pollinator:moth",
            "display_label": "hawk moth",
            "evidence_class": "literature",
            "confidence_score": 0.7,
            "confidence_label": "moderate",
            "source_table": "oc_graph.kg_edges",
            "source_pk": 5,
        },
    ]
}


def assert_no_sensitive_locality(value: Any) -> None:
    """Keep the route contract test independent of optional locality modules."""
    forbidden = {"latitude", "longitude", "coordinates", "locality", "exact_locality"}
    if isinstance(value, dict):
        assert not forbidden.intersection(value), value
        for item in value.values():
            assert_no_sensitive_locality(item)
    elif isinstance(value, list):
        for item in value:
            assert_no_sensitive_locality(item)


class FakeCursor:
    """Answers the exact SQL shapes the repository issues; anything else is a test failure."""

    def __init__(self, *, graph_present: bool = True) -> None:
        self.graph_present = graph_present
        self._rows: list[dict[str, Any]] = []
        self.statements: list[str] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        compact = " ".join(sql.split())
        self.statements.append(compact)
        if "to_regclass('oc_graph.kg_nodes')" in compact:
            self._rows = [
                {
                    "nodes_present": self.graph_present,
                    "edges_present": self.graph_present,
                }
            ]
        elif "FROM public.orchid_taxonomy WHERE id::text = %s" in compact:
            self._rows = [dict(t) for t in TAXA if str(t["id"]) == params[0]]
        elif "lower(scientific_name) = lower(%s)" in compact:
            wanted = params[0].lower()
            self._rows = [
                dict(t)
                for t in TAXA
                if t["scientific_name"].lower() == wanted
                or " ".join(t["scientific_name"].split()[:2]).lower() == wanted
            ]
        elif "FROM public.orchid_images" in compact:
            self._rows = list(IMAGES.get(params[0], []))
        elif "FROM oc_graph.kg_nodes n1" in compact:
            taxon_id = int(params[0].split(":", 1)[1])
            self._rows = list(GRAPH_EDGES.get(taxon_id, []))
        elif "lower(genus) = lower(%s) AND id::text <> %s" in compact:
            self._rows = [
                dict(t)
                for t in TAXA
                if t["genus"].lower() == params[0].lower() and str(t["id"]) != params[1]
            ]
        else:  # pragma: no cover - guards against silently accepting an unexpected query
            raise AssertionError(f"unexpected SQL: {compact}")

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


def fake_db_execute(*, cursor: FakeCursor | None):
    def _execute(callback):
        return callback(cursor)

    return _execute


def repository(cursor: FakeCursor | None = None) -> PostgresSpeciesRepository:
    return PostgresSpeciesRepository(
        fake_db_execute(cursor=cursor if cursor is not None else FakeCursor())
    )


@pytest.fixture()
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_service] = lambda: SpeciesDossierService(
        repository(), public_base_url="https://oc.test"
    )
    return TestClient(app)


# -- repository ---------------------------------------------------------------------------


def test_split_scientific_name_keeps_only_genus_and_lowercase_epithet():
    assert split_scientific_name("Phalaenopsis amabilis (L.) Blume") == (
        "Phalaenopsis",
        "amabilis",
    )
    assert split_scientific_name("Phalaenopsis") == ("Phalaenopsis", None)
    assert split_scientific_name("Phalaenopsis Blume") == ("Phalaenopsis", None)


def test_dossier_identity_media_and_graph_come_from_stored_rows_and_every_gap_is_named():
    dossier = repository().get_dossier("101")
    assert dossier is not None
    assert dossier.identity.taxon_id == "101"
    assert dossier.identity.full_scientific_name == "Phalaenopsis amabilis (L.) Blume"
    assert dossier.identity.accepted_name == "Phalaenopsis amabilis"
    assert dossier.identity.display_name == "Phalaenopsis amabilis"
    assert dossier.identity.authorship == "(L.) Blume"
    assert (
        dossier.identity.genus,
        dossier.identity.specific_epithet,
        dossier.identity.rank,
    ) == ("Phalaenopsis", "amabilis", "species")
    assert dossier.identity.synonyms == []

    assert dossier.living_media.state == "provisional"
    assert [item["url"] for item in dossier.living_media.items] == [
        "https://images.example/1.jpg",
        "https://images.example/2.jpg",
    ]
    assert all(
        item["identification_state"] == "source_record_not_independently_verified"
        for item in dossier.living_media.items
    )
    assert [r.license for r in dossier.living_media.receipts] == [
        "CC-BY-NC-4.0",
        "CC-BY-SA-4.0",
    ]
    assert dossier.living_media.receipts[1].attribution == "B. Photographer"

    assert dossier.knowledge_graph.state == "available"
    assert dossier.knowledge_graph.items[0]["edge_type"] == "pollinated_by"
    assert dossier.knowledge_graph.receipts[0].record_id == "5"

    for name in [
        "nomenclature",
        "protologue",
        "type_material",
        "historical_media",
        "morphology",
        "distribution",
        "ecology",
        "phenology",
        "pollinators",
        "mycorrhizae",
        "conservation",
        "literature",
        "cultivation",
        "calyx_narrative",
        "research_gaps",
    ]:
        section = getattr(dossier, name)
        assert section.state == "unavailable", name
        assert section.unavailable_reason, name
    assert "not evidence of absence" in dossier.nomenclature.unavailable_reason
    assert "human scientific review" in dossier.calyx_narrative.unavailable_reason

    assert dossier.related_species == [
        {
            "taxon_id": "102",
            "display_name": "Phalaenopsis aphrodite Rchb.f.",
            "relation": "same_genus",
        }
    ]
    assert dossier.matrix_url == "/orchid-identification?taxon_id=101"
    assert dossier.provenance[0].source_id == "public.orchid_taxonomy"


def test_dossier_never_emits_locality_or_coordinates():
    dossier = repository().get_dossier("101")
    payload = dossier.model_dump(mode="json")
    assert_no_sensitive_locality(payload)  # raises on any protected key at any depth
    assert dossier.atlas.layers == []
    assert "occurrences" in dossier.atlas.unavailable_layers
    assert "protected" in dossier.distribution.unavailable_reason
    assert not re.search(
        r"\b-?\d{1,2}\.\d{3,}\b", str(payload)
    )  # no coordinate-looking numbers anywhere


def test_dossier_without_media_or_graph_tables_is_honest_not_empty_handed():
    dossier = repository(FakeCursor(graph_present=False)).get_dossier("103")
    assert dossier is not None
    assert dossier.living_media.state == "unavailable"
    assert "No licensed living media" in dossier.living_media.unavailable_reason
    assert dossier.knowledge_graph.state == "unavailable"
    assert "not provisioned" in dossier.knowledge_graph.unavailable_reason
    assert dossier.related_species == []


def test_unknown_taxon_and_missing_database_return_none():
    assert repository().get_dossier("999") is None
    assert repository().get_atlas("999") is None
    assert repository().resolve_taxon_id("999") is None
    unconfigured = PostgresSpeciesRepository(fake_db_execute(cursor=None))
    assert unconfigured.get_dossier("101") is None
    assert unconfigured.resolve_name("Phalaenopsis amabilis") == []


def test_resolve_name_matches_accepted_binomial_only_and_never_claims_synonymy():
    hits = repository().resolve_name("Phalaenopsis amabilis")
    assert hits == [("101", "Phalaenopsis amabilis", "accepted_name")]
    assert repository().resolve_name("Masdevallia vampira") == []
    assert repository().resolve_partner_slug("iospe", "dracvampira") == []


# -- routes ---------------------------------------------------------------------------------


def test_dossier_route_serves_the_contract_the_species_page_consumes(client):
    resp = client.get("/api/platform/species/101/dossier")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["contract_version"] == "oc-species-dossier-v1"
    assert body["identity"]["display_name"] == "Phalaenopsis amabilis"
    assert (
        body["identity"]["full_scientific_name"] == "Phalaenopsis amabilis (L.) Blume"
    )
    assert body["atlas"]["contract_version"] == "oc-species-atlas-v1"
    assert body["living_media"]["state"] == "provisional"
    assert body["pollinators"]["state"] == "unavailable"
    assert_no_sensitive_locality(body)


def test_atlas_route_reports_every_layer_unavailable(client):
    resp = client.get("/api/platform/species/101/atlas")
    assert resp.status_code == 200, resp.text
    assert resp.json()["layers"] == []
    assert resp.json()["unavailable_layers"] == [
        "occurrences",
        "range",
        "protected_areas",
        "elevation",
        "climate",
    ]


def test_unknown_taxon_is_404_on_both_routes(client):
    assert client.get("/api/platform/species/999/dossier").status_code == 404
    assert client.get("/api/platform/species/999/atlas").status_code == 404


def test_resolve_route_resolves_id_and_accepted_name_and_reports_unresolved_honestly(
    client,
):
    by_id = client.get(
        "/api/platform/federation/resolve-species", params={"taxon_id": "101"}
    ).json()
    assert (by_id["status"], by_id["match_state"], by_id["taxon_id"]) == (
        "resolved",
        "taxon_id",
        "101",
    )
    assert by_id["canonical_dossier_url"] == "https://oc.test/species/101"

    by_name = client.get(
        "/api/platform/federation/resolve-species",
        params={"name": "Phalaenopsis amabilis Blume"},
    ).json()
    assert (by_name["status"], by_name["match_state"], by_name["matched_name"]) == (
        "resolved",
        "accepted_name",
        "Phalaenopsis amabilis",
    )

    unresolved = client.get(
        "/api/platform/federation/resolve-species",
        params={"name": "Masdevallia vampira"},
    ).json()
    assert unresolved["status"] == "unresolved"
    assert "No canonical accepted name or synonym match" in unresolved["explanation"]

    assert client.get("/api/platform/federation/resolve-species").status_code == 422


def test_routes_fail_closed_without_a_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    app = FastAPI()
    app.include_router(router)
    resp = TestClient(app).get("/api/platform/species/101/dossier")
    assert resp.status_code == 503
    assert resp.json()["detail"] == dossier_routes.DATABASE_UNCONFIGURED


def test_database_failure_is_503_not_a_fabricated_dossier(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    def _boom(callback):
        raise RuntimeError("connection refused")

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_service] = lambda: SpeciesDossierService(
        PostgresSpeciesRepository(_boom)
    )
    resp = TestClient(app).get("/api/platform/species/101/dossier")
    assert resp.status_code == 503
    assert resp.json()["detail"] == dossier_routes.SERVICE_UNAVAILABLE


def test_main_app_registers_species_dossier_routes():
    pytest.importorskip("psycopg", reason="app.main imports the full router set")
    from app.main import app as main_app

    paths = {route.path for route in main_app.routes}
    assert "/api/platform/species/{taxon_id}/dossier" in paths
    assert "/api/platform/species/{taxon_id}/atlas" in paths
    assert "/api/platform/federation/resolve-species" in paths
