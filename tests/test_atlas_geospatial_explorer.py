from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.atlas_intelligence import explorer
from app.atlas_intelligence.locality import resolve_location
from app.atlas_intelligence.occurrences import (
    MAX_SCAN_ROWS,
    BBox,
    InMemoryOccurrenceRepository,
    OccurrenceQuery,
    OccurrenceRecord,
    OccurrenceService,
    TTLCache,
    UnconfiguredOccurrenceRepository,
    build_where,
    cell_deg_for_zoom,
    decode_cursor,
    encode_cursor,
    repository_from_environment,
)

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
FIXED_NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)


def _record(
    occurrence_id: str, lat: float, lng: float, **extra: object
) -> OccurrenceRecord:
    defaults: dict[str, object] = {
        "scientific_name": "Dracula vampira",
        "genus": "Dracula",
        "taxon_id": "tx-dracula-vampira",
        "assessment_resolved": True,
        "dataset_name": "Synthetic test dataset",
        "license": "CC0-1.0",
        "year": 2001,
        "month": 3,
    }
    defaults.update(extra)
    return OccurrenceRecord(
        occurrence_id=occurrence_id,
        decimal_latitude=lat,
        decimal_longitude=lng,
        **defaults,
    )  # type: ignore[arg-type]


def _service(records: list[OccurrenceRecord]) -> OccurrenceService:
    return OccurrenceService(
        InMemoryOccurrenceRepository(
            records, source_id="test-fixture", label="Synthetic fixture"
        ),
        clock=lambda: FIXED_NOW,
    )


# --- locality parity with the frontend ---------------------------------------------------


def _vectors() -> list[dict]:
    return json.loads(
        (CONTRACTS / "atlas_locality_policy_vectors_v1.json").read_text()
    )["vectors"]


@pytest.mark.parametrize("vector", _vectors(), ids=lambda v: v["name"])
def test_locality_policy_matches_frontend_vectors(vector: dict) -> None:
    given = vector["input"]
    shown = resolve_location(
        lat=given["lat"],
        lng=given["lng"],
        iucn_code=given.get("iucnCode"),
        conservation_status=given.get("conservationStatus"),
        coordinate_uncertainty_m=given.get("coordinateUncertaintyM"),
        assessment_resolved=given.get("assessmentResolved"),
        access=vector["access"],
    )
    expected = vector["expected"]
    assert shown.lat == pytest.approx(expected["lat"], abs=1e-9)
    assert shown.lng == pytest.approx(expected["lng"], abs=1e-9)
    assert shown.policy.generalised is expected["generalised"]
    assert shown.policy.cell_deg == pytest.approx(expected["cell_deg"])
    assert shown.policy.reason == expected["reason"]
    assert shown.policy.locality_text_allowed is expected["locality_text_allowed"]
    assert shown.policy.notice == expected["notice"]


# --- geometry ----------------------------------------------------------------------------


def test_bbox_parse_and_antimeridian_split() -> None:
    box = BBox.parse("170,-30,-170,-10")
    assert box.crosses_antimeridian
    assert box.lon_ranges() == ((170.0, 180.0), (-180.0, -170.0))
    assert box.contains(-20, 175) and box.contains(-20, -175)
    assert not box.contains(-20, 0)


@pytest.mark.parametrize(
    "raw",
    ["", "1,2,3", "a,b,c,d", "0,10,10,5", "0,0,0,10", "0,-95,10,10", "-190,0,10,10"],
)
def test_bbox_rejects_malformed_input(raw: str) -> None:
    with pytest.raises(ValueError):
        BBox.parse(raw)


def test_cluster_ladder_coarse_cells_are_whole_degrees() -> None:
    # Whole-degree coarse cells nest every policy cell; that is the SQL safety argument.
    assert [cell_deg_for_zoom(z) for z in range(5)] == [20.0, 10.0, 5.0, 2.0, 1.0]
    assert cell_deg_for_zoom(30) == 0.05


def test_cursor_round_trip_and_rejection() -> None:
    assert decode_cursor(encode_cursor("occ:42/α")) == "occ:42/α"
    with pytest.raises(ValueError):
        decode_cursor("***")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"zoom": 30},
        {"limit": 0},
        {"limit": 5000},
        {"year_from": 2000, "year_to": 1990},
        {"months": (13,)},
        {"genus": "dracula; drop table"},
        {"taxon_id": "x' or 1=1"},
    ],
)
def test_query_validation_fails_closed(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        OccurrenceQuery(bbox=BBox.world(), **kwargs)


# --- service behaviour -------------------------------------------------------------------


def test_points_mode_projects_threatened_records_and_withholds_locality() -> None:
    records = [
        _record(
            "a",
            -3.98765,
            -79.20456,
            iucn_category="CR",
            locality="Trail above the river",
            event_date="2001-03-04",
        ),
        _record("b", -3.5, -79.1, locality="Public botanical garden"),
    ]
    response = _service(records).query(
        OccurrenceQuery(bbox=BBox(-80, -5, -78, -2), zoom=9, limit=50)
    )
    assert response.mode == "points"
    by_id = {p.occurrenceID: p for p in response.points}
    protected = by_id["a"]
    assert (protected.decimalLatitude, protected.decimalLongitude) == (-3.5, -79.5)
    assert protected.generalised and protected.generalisationReason == "iucn-threatened"
    assert (
        protected.locality is None
        and protected.eventDate is None
        and protected.references is None
    )
    assert by_id["b"].locality == "Public botanical garden"
    assert response.locality.generalised_count == 1
    assert response.locality.locality_withheld_count == 1
    assert response.attribution[0].dataset_name == "Synthetic test dataset"


def test_low_zoom_clusters_never_expose_a_protected_site() -> None:
    lone_cr = _record("cr", -3.98765, -79.20456, iucn_category="CR")
    response = _service([lone_cr]).query(
        OccurrenceQuery(bbox=BBox.world(), zoom=7.5, limit=500, mode="clusters")
    )
    assert response.mode == "clusters"
    [cluster] = response.clusters
    # A one-record cluster sits on the generalised position, never the precise one.
    assert (cluster.latitude, cluster.longitude) == (-3.5, -79.5)
    assert cluster.generalised_count == 1


def test_auto_mode_clusters_at_world_zoom_and_points_when_zoomed_in() -> None:
    records = [_record(f"r{i:03d}", -1 + i * 0.001, -78 + i * 0.001) for i in range(30)]
    service = _service(records)
    world = service.query(OccurrenceQuery(bbox=BBox.world(), zoom=1))
    assert world.mode == "clusters" and world.cell_deg == 10.0
    assert sum(c.count for c in world.clusters) == 30
    local = service.query(OccurrenceQuery(bbox=BBox(-79, -2, -77, 0), zoom=10))
    assert local.mode == "points" and len(local.points) == 30


def test_points_mode_paginates_with_keyset_cursor() -> None:
    records = [_record(f"r{i:03d}", 5 + i * 0.01, 5) for i in range(25)]
    service = _service(records)
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        page = service.query(
            OccurrenceQuery(
                bbox=BBox.world(), zoom=10, limit=10, cursor=cursor, mode="points"
            )
        )
        seen.extend(p.occurrenceID for p in page.points)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == [f"r{i:03d}" for i in range(25)]


def test_filters_taxon_time_and_month() -> None:
    records = [
        _record("1", 1, 1, year=1890, month=1),
        _record("2", 1, 1.1, year=1999, month=6),
        _record(
            "3",
            1,
            1.2,
            year=2015,
            month=6,
            taxon_id="tx-other",
            genus="Masdevallia",
            scientific_name="Masdevallia veitchiana",
        ),
        _record("4", 0, 0, year=2015, month=6),  # 0,0 is a data error and never drawn
    ]
    service = _service(records)
    q = lambda **kw: service.query(
        OccurrenceQuery(bbox=BBox.world(), zoom=12, mode="points", **kw)
    )
    assert [p.occurrenceID for p in q(year_from=1950).points] == ["2", "3"]
    assert [p.occurrenceID for p in q(genus="Masdevallia").points] == ["3"]
    assert [
        p.occurrenceID for p in q(taxon_id="tx-dracula-vampira", months=(6,)).points
    ] == ["2"]
    assert [
        p.occurrenceID for p in q(scientific_name="masdevallia VEITCHIANA").points
    ] == ["3"]


def test_cache_hits_and_expires() -> None:
    now = [0.0]
    service = OccurrenceService(
        InMemoryOccurrenceRepository([_record("a", 1, 1)], source_id="fx", label="fx"),
        cache=TTLCache(ttl_seconds=10, clock=lambda: now[0]),
        clock=lambda: FIXED_NOW,
    )
    query = OccurrenceQuery(bbox=BBox.world(), zoom=2)
    assert service.query(query).cache == "miss"
    assert service.query(query).cache == "hit"
    now[0] = 11
    assert service.query(query).cache == "miss"


def test_unconfigured_source_returns_nothing_and_says_why() -> None:
    service = OccurrenceService(
        UnconfiguredOccurrenceRepository(), clock=lambda: FIXED_NOW
    )
    response = service.query(OccurrenceQuery(bbox=BBox.world()))
    assert response.source.state == "source_not_configured"
    assert (
        response.points == []
        and response.clusters == []
        and response.total_in_view == 0
    )
    summary = service.summary(OccurrenceQuery(bbox=BBox.world()))
    assert summary.total == 0 and summary.by_year == []


def test_summary_buckets_and_month_semantics() -> None:
    records = [
        _record("1", 1, 1, year=2001, month=3),
        _record("2", 1, 1, year=2001, month=4, basis_of_record="PreservedSpecimen"),
    ]
    summary = _service(records).summary(OccurrenceQuery(bbox=BBox.world()))
    assert summary.total == 2 and summary.total_is_exact
    assert [(b.key, b.count) for b in summary.by_year] == [("2001", 2)]
    assert len(summary.by_month) == 12 and summary.by_month[2].count == 1
    assert "not flowering phenology" in summary.month_semantics


def test_repository_from_environment_is_fail_closed() -> None:
    assert repository_from_environment({}).describe().state == "source_not_configured"
    missing_db = repository_from_environment(
        {"ATLAS_OCCURRENCE_RELATION": "oc_atlas.public_occurrences"}
    )
    assert "DATABASE_URL" in (missing_db.describe().detail or "")
    bad = repository_from_environment(
        {"ATLAS_OCCURRENCE_RELATION": "x; drop", "DATABASE_URL": "postgresql://x"}
    )
    assert bad.describe().state == "source_not_configured"


def test_sql_where_is_parameterised_and_handles_antimeridian() -> None:
    query = OccurrenceQuery(
        bbox=BBox(170, -30, -170, -10), genus="Dendrobium", months=(1, 2)
    )
    where, params = build_where(query, after_id="occ-9")
    assert "Dendrobium" not in where and "%s" in where
    assert where.count("decimal_longitude BETWEEN %s AND %s") == 2
    assert params[:6] == [-30, -10, 170, 180.0, -180.0, -170]
    assert params[-3:] == ["Dendrobium", [1, 2], "occ-9"]
    postgis_where, postgis_params = build_where(query, use_postgis=True)
    assert (
        postgis_where.count("ST_MakeEnvelope") == 2 and len(postgis_params) == 2 + 8 + 2
    )


# --- API ---------------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    records = [
        _record("a", -3.98765, -79.20456, iucn_category="EN"),
        _record("b", -2.1, -78.9),
    ]
    explorer.reset_occurrence_service(_service(records))
    app = FastAPI()
    app.include_router(explorer.router)
    yield TestClient(app)
    explorer.reset_occurrence_service(None)


def test_api_query_points_and_validation(client: TestClient) -> None:
    ok = client.get(
        "/atlas/occurrences/query", params={"bbox": "-80,-5,-78,-1", "zoom": 9}
    )
    assert ok.status_code == 200
    body = ok.json()
    assert (
        body["contract_version"] == "oc-atlas-occurrence-query-v1"
        and body["mode"] == "points"
    )
    protected = next(p for p in body["points"] if p["occurrenceID"] == "a")
    assert protected["generalisationCellDeg"] == 0.5
    assert (
        client.get("/atlas/occurrences/query", params={"bbox": "1,2,3"}).status_code
        == 422
    )
    assert (
        client.get("/atlas/occurrences/query", params={"genus": "lower"}).status_code
        == 422
    )


def test_api_summary_taxa_catalog_and_capabilities(client: TestClient) -> None:
    assert client.get("/atlas/occurrences/summary").json()["total"] == 2
    taxa = client.get("/atlas/taxa/search", params={"q": "drac"}).json()
    assert taxa["matches"][0]["taxon_id"] == "tx-dracula-vampira"
    catalog = client.get("/atlas/catalog/layers").json()
    statuses = {layer["status"] for layer in catalog["layers"]}
    assert {"operational", "planned", "blocked"} <= statuses
    planned_only = client.get(
        "/atlas/catalog/layers", params={"status": "planned"}
    ).json()["layers"]
    assert planned_only and all(
        layer["status"] == "planned" and layer.get("blocker") for layer in planned_only
    )
    capabilities = client.get("/atlas/capabilities").json()
    by_id = {c["capability_id"]: c for c in capabilities["capabilities"]}
    assert by_id["atlas.occurrences.query"]["availability"] == {
        "state": "available",
        "probed": True,
    }
    assert by_id["genus.profile"]["availability"]["state"] == "not_probed"
    assert (
        client.get("/atlas/capabilities", params={"module_id": "nope"}).status_code
        == 404
    )


def test_api_store_failure_is_503_not_500() -> None:
    class Broken(InMemoryOccurrenceRepository):
        def count(self, query, *, cap):  # type: ignore[override]
            raise RuntimeError("connection reset with secret dsn")

    explorer.reset_occurrence_service(
        OccurrenceService(Broken([], source_id="b", label="b"))
    )
    app = FastAPI()
    app.include_router(explorer.router)
    try:
        response = TestClient(app).get("/atlas/occurrences/query")
        assert response.status_code == 503
        assert "secret" not in response.text
    finally:
        explorer.reset_occurrence_service(None)


# --- contracts ---------------------------------------------------------------------------


def test_contracts_are_internally_consistent() -> None:
    catalog = json.loads((CONTRACTS / "atlas_layer_catalog_v1.json").read_text())
    vocabulary = set(catalog["status_vocabulary"])
    ids = [layer["layer_id"] for layer in catalog["layers"]]
    assert len(ids) == len(set(ids))
    for layer in catalog["layers"]:
        assert layer["status"] in vocabulary
        if layer["status"] in {"planned", "blocked"}:
            assert layer.get("blocker"), layer["layer_id"]

    capabilities = json.loads(
        (CONTRACTS / "atlas_module_capabilities_v1.json").read_text()
    )
    from runtime.brain_capability_registry import (
        CapabilityStatus,  # canonical vocabulary
    )

    allowed = set(CapabilityStatus.__args__)  # type: ignore[attr-defined]
    assert set(capabilities["status_vocabulary"]) == allowed
    known = {c["capability_id"] for c in capabilities["capabilities"]}
    for capability in capabilities["capabilities"]:
        assert capability["declared_status"] in allowed
        for field in (
            "module_id",
            "output_contract",
            "required_permissions",
            "canonical_identifiers",
            "provenance",
            "error_behavior",
            "fallback",
        ):
            assert capability.get(field) is not None, (
                capability["capability_id"],
                field,
            )
        assert set(capability["canonical_identifiers"]) <= set(
            capabilities["identifier_systems"]
        )
    for workflow in capabilities["workflows"]:
        assert set(workflow["steps"]) <= known


def test_max_scan_rows_is_bounded() -> None:
    assert MAX_SCAN_ROWS <= 50_000
