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
        {
            "id": 9003,
            "image_url": "https://images.example/unlicensed.jpg",
            "image_source": "unknown",
            "image_license": None,
            "image_rights_holder": None,
            "observer_name": None,
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
            "is_active": True,
            "from_is_active": True,
            "to_is_active": True,
        },
        {
            "edge_type": "withdrawn_relation",
            "node_type": "pollinator",
            "canonical_key": "pollinator:withdrawn",
            "display_label": "withdrawn pollinator",
            "evidence_class": "historical",
            "confidence_score": 0.9,
            "confidence_label": "high",
            "source_table": "oc_graph.kg_edges",
            "source_pk": 6,
            "is_active": False,
            "from_is_active": True,
            "to_is_active": True,
        },
        {
            "edge_type": "supported_by_evidence",
            "node_type": "evidence",
            "canonical_key": "evidence:yong-gee:4242:notes",
            "display_label": "Phalaenopsis amabilis — notes",
            "evidence_class": "compiled_specialist_source",
            "confidence_score": 1.0,
            "confidence_label": "source_faithful",
            "source_table": "federated.gary_yong_gee_workbook",
            "source_pk": "yong-gee:4242:notes",
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

    def __init__(
        self,
        *,
        graph_present: bool = True,
        evidence: dict[int, list[dict[str, Any]]] | None = None,
        honor_evidence_type_filter: bool = True,
    ) -> None:
        self.graph_present = graph_present
        self.evidence = evidence or {}
        self.honor_evidence_type_filter = honor_evidence_type_filter
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
            rows = list(IMAGES.get(params[0], []))
            if "NULLIF(BTRIM(image_license), '') IS NOT NULL" in compact:
                rows = [
                    row for row in rows if str(row.get("image_license") or "").strip()
                ]
            self._rows = rows
        elif "FROM oc_graph.kg_nodes t JOIN oc_graph.kg_edges e" in compact:
            assert "e.edge_type = 'supported_by_evidence'" in compact
            assert "ev.node_type = 'evidence'" in compact
            taxon_id = int(params[0].split(":", 1)[1])
            rows = [
                row
                for row in self.evidence.get(taxon_id, [])
                if row["source_table"] == params[1] and row.get("is_active", True)
            ]
            if self.honor_evidence_type_filter:
                assert "NOT IN (%s, %s, %s, %s)" in compact
                rows = [
                    row
                    for row in rows
                    if row["payload_json"].get("evidence_type") not in params[2:6]
                ]
            self._rows = rows[: params[6]]
        elif "FROM oc_graph.kg_nodes n1" in compact:
            taxon_id = int(params[0].split(":", 1)[1])
            rows = list(GRAPH_EDGES.get(taxon_id, []))
            if "e.edge_type <> 'supported_by_evidence'" in compact:
                rows = [
                    row for row in rows if row["edge_type"] != "supported_by_evidence"
                ]
            if "n1.is_active IS TRUE" in compact:
                rows = [
                    row
                    for row in rows
                    if row.get("is_active", True)
                    and row.get("from_is_active", True)
                    and row.get("to_is_active", True)
                ]
            self._rows = rows
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
    assert dossier.taxon_id == "101"
    assert dossier.display_name == "Phalaenopsis amabilis"
    assert dossier.full_scientific_name == "Phalaenopsis amabilis (L.) Blume"
    assert dossier.accepted_name == "Phalaenopsis amabilis"
    assert dossier.atlas_summary.state == "unavailable"
    assert dossier.identification_matrix.state == "unavailable"
    assert dossier.freshness.state == "unknown"
    assert "atlas_summary" in dossier.unavailable_sections

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
    assert body["taxon_id"] == "101"
    assert body["display_name"] == "Phalaenopsis amabilis"
    assert body["full_scientific_name"] == "Phalaenopsis amabilis (L.) Blume"
    assert body["accepted_name"] == "Phalaenopsis amabilis"
    assert body["freshness"]["state"] == "unknown"
    assert "identification_matrix" in body["unavailable_sections"]
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

    partner_aliases = client.get(
        "/api/platform/federation/resolve-species",
        params={"partner": "iospe", "slug": "dracvampira"},
    ).json()
    assert partner_aliases["status"] == "invalid"
    assert partner_aliases["partner_slug"] == "iospe"

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


def test_database_http_503_is_sanitized(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")

    def _boom(callback):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=503, detail="connection refused at db.internal:5432"
        )

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


# -- federated compiled-specialist evidence (Gary Yong Gee) --------------------------------

FRONTEND_ENVELOPE_KEYS = [
    "contract_version",
    "generated_at",
    "identity",
    "nomenclature",
    "protologue",
    "type_material",
    "historical_media",
    "living_media",
    "morphology",
    "distribution",
    "ecology",
    "phenology",
    "pollinators",
    "mycorrhizae",
    "conservation",
    "literature",
    "cultivation",
    "knowledge_graph",
    "calyx_narrative",
    "research_gaps",
    "atlas",
    "related_species",
    "matrix_url",
    "partner_references",
    "provenance",
]
FRONTEND_SECTION_KEYS = {"state", "summary", "items", "receipts", "unavailable_reason"}
FRONTEND_RECEIPT_KEYS = {
    "source_id",
    "source_name",
    "source_url",
    "record_id",
    "retrieved_at",
    "license",
    "attribution",
    "evidence_state",
    "confidence",
    "notes",
}
DISTRIBUTION_TEXT = (
    "Endemic to the Kinabalu massif, lower montane forest near Kundasang"
)
HABITAT_TEXT = "Epiphyte on mossy trunks in cloud forest at 1500 m"
LONG_MORPHOLOGY = "Sepals ovate, acuminate. " * 120


def yong_gee_kg_rows(
    taxon_pk: str, cleaned: dict[str, str | None]
) -> list[dict[str, Any]]:
    """KG node rows exactly as the Yong Gee adapter (#1617) would publish them."""
    from runtime.federated_sources.yong_gee import (
        TaxonResolution,
        YongGeeRecord,
        _produce_yong_gee_evidence,
        evidence_rows,
    )

    record = YongGeeRecord(
        source_record_id="4242",
        scientific_name="Phalaenopsis amabilis",
        source_digest="d" * 64,
        raw={},
        cleaned={"websiteSlug": "phalaenopsis-amabilis", **cleaned},
    )
    resolution = TaxonResolution(
        source_record_id="4242",
        scientific_name="Phalaenopsis amabilis",
        state="matched",
        taxon_pk=taxon_pk,
    )
    nodes, edges = _produce_yong_gee_evidence(evidence_rows([(record, resolution)]))
    assert all(edge.edge_type == "supported_by_evidence" for edge in edges)
    return [
        {
            "source_table": node.source_table,
            "source_pk": node.source_pk,
            "payload_json": dict(node.payload),
            "updated_at": "2026-09-20T12:00:00+00:00",
        }
        for node in nodes
    ]


YONG_GEE_CLEANED = {
    "synonym": "Epidendrum amabile L.",
    "publicationsp": "Bijdr. Fl. Ned. Ind. 7: 294",
    "pubyrsp": "1825",
    "commonName": "Moon orchid",
    "etymology": "Latin amabilis, lovely.",
    "characteristicsp": LONG_MORPHOLOGY,
    "scent": "Faintly sweet.",
    "season": "Flowers in winter and spring.",
    "referencesp": "Christenson, E.A. (2001) Phalaenopsis: a monograph.",
    "notes": "A parent of many hybrids.",
    "distributionsp": DISTRIBUTION_TEXT,
    "habitat": HABITAT_TEXT,
}


def federated_repository(**cursor_kwargs: Any) -> PostgresSpeciesRepository:
    evidence = {101: yong_gee_kg_rows("101", YONG_GEE_CLEANED)}
    return repository(FakeCursor(evidence=evidence, **cursor_kwargs))


def _strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)] + list(value)
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return [value] if isinstance(value, str) else []


def test_yong_gee_evidence_populates_provisional_sections_with_receipts():
    from app.species_dossier import repository as dossier_repository
    from runtime.federated_sources import yong_gee

    assert dossier_repository.YONG_GEE_SOURCE_TABLE == yong_gee.SOURCE_TABLE
    assert dossier_repository.YONG_GEE_SOURCE_NAME == yong_gee.SOURCE_NAME

    dossier = federated_repository().get_dossier("101")
    assert dossier is not None
    expected_types = {
        "nomenclature": {
            "nomenclature",
            "nomenclatural_publication",
            "publication_year",
            "common_name",
            "etymology",
        },
        "morphology": {"morphology", "scent"},
        "phenology": {"phenology"},
        "literature": {"bibliography"},
    }
    for name, types in expected_types.items():
        section = getattr(dossier, name)
        assert section.state == "provisional", name
        assert section.unavailable_reason is None
        assert (
            "Compiled by Gary Yong Gee; not independently verified" in section.summary
        )
        assert {item["evidence_type"] for item in section.items} == types
        assert all(item["evidence_state"] == "provisional" for item in section.items)
        assert len(section.receipts) == len(section.items)
        for receipt in section.receipts:
            assert receipt.source_id == "federated.gary_yong_gee_workbook"
            assert receipt.source_name == "Gary Yong Gee Orchid Database"
            assert (
                str(receipt.source_url)
                == "https://www.yonggee.name/phalaenopsis-amabilis"
            )
            assert receipt.record_id.startswith("yong-gee:4242:")
            assert receipt.attribution == "Gary Yong Gee (compiler)"
            assert receipt.evidence_state == "provisional"
            assert (
                receipt.confidence is None
            )  # stored score is source faithfulness only
            assert receipt.license is None  # no licence is stored; none is invented
            assert receipt.retrieved_at is not None
            assert "underlying_citation_status=present_in_record" in receipt.notes
        assert name not in dossier.unavailable_sections

    assert dossier.phenology.items[0]["excerpt"] == "Flowers in winter and spring."
    morphology = next(
        i for i in dossier.morphology.items if i["evidence_type"] == "morphology"
    )
    assert morphology["excerpt_truncated"] is True
    assert morphology["excerpt"].endswith("[...]")
    assert len(morphology["excerpt"]) <= 1200

    # Free-text notes can name a locality in prose, so they are withheld with
    # distribution and habitat until a locality-sensitivity review.
    assert not [i for i in dossier.knowledge_graph.items if "excerpt" in i]
    assert dossier.knowledge_graph.items[0]["edge_type"] == "pollinated_by"
    assert "compiled specialist" not in (dossier.knowledge_graph.summary or "")
    assert "A parent of many hybrids." not in dossier.model_dump_json()

    # Sections without evidence keep the existing honest reason.
    for name in [
        "protologue",
        "type_material",
        "ecology",
        "pollinators",
        "research_gaps",
    ]:
        assert getattr(dossier, name).state == "unavailable"
        assert name in dossier.unavailable_sections
    assert dossier.calyx_narrative.state == "unavailable"


def test_taxon_without_federated_evidence_is_unchanged():
    dossier = federated_repository().get_dossier("102")
    assert dossier is not None
    for name in ["nomenclature", "morphology", "phenology", "literature"]:
        section = getattr(dossier, name)
        assert section.state == "unavailable"
        assert "not evidence of absence" in section.unavailable_reason
        assert name in dossier.unavailable_sections


def test_no_graph_tables_means_no_federated_query():
    cursor = FakeCursor(
        graph_present=False, evidence={101: yong_gee_kg_rows("101", YONG_GEE_CLEANED)}
    )
    dossier = repository(cursor).get_dossier("101")
    assert dossier.nomenclature.state == "unavailable"
    assert not any("supported_by_evidence" in sql for sql in cursor.statements)


@pytest.mark.parametrize("honor_sql_filter", [True, False])
def test_federated_distribution_and_habitat_are_never_emitted(honor_sql_filter):
    dossier = federated_repository(
        honor_evidence_type_filter=honor_sql_filter
    ).get_dossier("101")
    payload = dossier.model_dump(mode="json")
    text = "\n".join(_strings(payload))
    for sensitive in (
        DISTRIBUTION_TEXT,
        HABITAT_TEXT,
        "Kinabalu",
        "Kundasang",
        "1500 m",
    ):
        assert sensitive not in text
    assert all(
        item.get("evidence_type") not in {"distribution", "habitat"}
        for section in payload.values()
        if isinstance(section, dict)
        for item in section.get("items", [])
    )
    assert dossier.distribution.state == "unavailable"
    assert (
        "Distribution and habitat descriptions from federated sources are withheld "
        "pending locality-sensitivity review."
        in dossier.distribution.unavailable_reason
    )
    assert dossier.ecology.state == "unavailable"
    assert_no_sensitive_locality(payload)
    assert not re.search(r"\b-?\d{1,2}\.\d{3,}\b", str(payload))


def test_coordinate_looking_excerpts_are_withheld_from_any_section():
    rows = yong_gee_kg_rows(
        "101",
        {
            "season": "Collected at 5.9804 N, 116.0735 E in March.",
            "scent": "Noted near 6°05'N 116°33'E.",
        },
    )
    dossier = repository(FakeCursor(evidence={101: rows})).get_dossier("101")
    assert dossier.phenology.state == "unavailable"
    assert dossier.morphology.state == "unavailable"
    assert "116" not in str(dossier.model_dump(mode="json"))


def test_federated_payload_still_satisfies_the_frontend_contract(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_service] = lambda: SpeciesDossierService(
        federated_repository(), public_base_url="https://oc.test"
    )
    resp = TestClient(app).get("/api/platform/species/101/dossier")
    assert resp.status_code == 200
    body = resp.json()
    assert set(FRONTEND_ENVELOPE_KEYS) <= set(body)
    sections = [
        key
        for key in FRONTEND_ENVELOPE_KEYS
        if isinstance(body[key], dict) and "state" in body[key] and key != "atlas"
    ]
    assert "nomenclature" in sections and "knowledge_graph" in sections
    for key in sections:
        section = body[key]
        assert FRONTEND_SECTION_KEYS <= set(section), key
        assert section["state"] in {
            "available",
            "provisional",
            "conflicting",
            "modeled",
            "inferred",
            "unavailable",
        }
        assert isinstance(section["items"], list)
        for receipt in section["receipts"]:
            assert FRONTEND_RECEIPT_KEYS <= set(receipt), key
    assert body["nomenclature"]["state"] == "provisional"
    assert (
        body["literature"]["receipts"][0]["attribution"] == "Gary Yong Gee (compiler)"
    )
    assert_no_sensitive_locality(body)


def test_evidence_edges_are_not_listed_as_graph_relationships():
    dossier = repository().get_dossier("101")
    assert dossier.knowledge_graph.state == "available"  # no federated notes here
    assert [item["edge_type"] for item in dossier.knowledge_graph.items] == [
        "pollinated_by"
    ]
    assert all(
        receipt.record_id != "yong-gee:4242:notes"
        for receipt in dossier.knowledge_graph.receipts
    )
