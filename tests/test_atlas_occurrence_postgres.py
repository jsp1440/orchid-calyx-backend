"""Spatial query tests against a real PostgreSQL server.

Opt-in: set ATLAS_TEST_DATABASE_URL to a disposable database. The test creates
and drops its own schema; it never touches production relations.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from app.atlas_intelligence.occurrences import (
    BBox,
    OccurrenceQuery,
    OccurrenceService,
    PostgresOccurrenceRepository,
)

DSN = os.getenv("ATLAS_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not DSN, reason="ATLAS_TEST_DATABASE_URL not set")

ROWS: list[tuple[Any, ...]] = [
    # occurrence_id, taxon_id, name, genus, lat, lng, unc, year, month, iucn, resolved, locality, dataset
    (
        "o1",
        "t1",
        "Dracula vampira",
        "Dracula",
        -3.98765,
        -79.20456,
        None,
        1890,
        1,
        "CR",
        True,
        "Ridge trail",
        "Herbarium A",
    ),
    (
        "o2",
        "t1",
        "Dracula vampira",
        "Dracula",
        -3.6,
        -79.1,
        50.0,
        2005,
        6,
        None,
        True,
        "Garden",
        "Herbarium A",
    ),
    (
        "o3",
        "t2",
        "Dendrobium kingianum",
        "Dendrobium",
        -17.5,
        179.5,
        None,
        2015,
        9,
        None,
        True,
        None,
        "Survey B",
    ),
    (
        "o4",
        "t2",
        "Dendrobium kingianum",
        "Dendrobium",
        -17.5,
        -179.5,
        None,
        2016,
        9,
        None,
        True,
        None,
        "Survey B",
    ),
    (
        "o5",
        "t3",
        "Ophrys apifera",
        "Ophrys",
        0.0,
        0.0,
        None,
        2010,
        5,
        None,
        True,
        None,
        "Survey B",
    ),
    (
        "o6",
        "t3",
        "Ophrys apifera",
        "Ophrys",
        51.5,
        -0.12,
        None,
        2019,
        6,
        None,
        False,
        "Meadow",
        "Survey C",
    ),
]


@pytest.fixture()
def repo() -> Iterator[PostgresOccurrenceRepository]:
    psycopg = pytest.importorskip("psycopg")
    from psycopg.rows import dict_row

    schema = f"atlas_test_{uuid.uuid4().hex[:8]}"

    def db_execute(callback: Any) -> Any:
        with psycopg.connect(DSN, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                result = callback(cur)
            conn.commit()
            return result

    def setup(cur: Any) -> None:
        cur.execute(f"CREATE SCHEMA {schema}")
        cur.execute(
            f"""
            CREATE TABLE {schema}.public_occurrences (
              occurrence_id text PRIMARY KEY, taxon_id text, scientific_name text, genus text,
              decimal_latitude double precision, decimal_longitude double precision,
              coordinate_uncertainty_in_meters double precision, country_code text,
              year int, month int, event_date text, basis_of_record text, dataset_name text,
              institution_code text, license text, rights_holder text, references_uri text,
              iucn_category text, conservation_status text, assessment_resolved boolean, locality text
            )
            """
        )
        cur.execute(
            f"CREATE INDEX ON {schema}.public_occurrences (decimal_latitude, decimal_longitude)"
        )
        for row in ROWS:
            (
                oid,
                tid,
                name,
                genus,
                lat,
                lng,
                unc,
                year,
                month,
                iucn,
                resolved,
                locality,
                dataset,
            ) = row
            cur.execute(
                f"""INSERT INTO {schema}.public_occurrences
                (occurrence_id, taxon_id, scientific_name, genus, decimal_latitude, decimal_longitude,
                 coordinate_uncertainty_in_meters, year, month, iucn_category, assessment_resolved, locality,
                 dataset_name, license, basis_of_record)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'CC-BY-4.0','PreservedSpecimen')""",
                (
                    oid,
                    tid,
                    name,
                    genus,
                    lat,
                    lng,
                    unc,
                    year,
                    month,
                    iucn,
                    resolved,
                    locality,
                    dataset,
                ),
            )
        cur.execute(
            f"CREATE TABLE {schema}.incomplete (occurrence_id text, decimal_latitude float)"
        )

    db_execute(setup)
    try:
        yield PostgresOccurrenceRepository(db_execute, f"{schema}.public_occurrences")
    finally:
        db_execute(lambda cur: cur.execute(f"DROP SCHEMA {schema} CASCADE"))


def test_describe_verifies_column_contract(repo: PostgresOccurrenceRepository) -> None:
    assert repo.describe().state == "available"
    incomplete = PostgresOccurrenceRepository(
        repo._db, repo._relation.replace("public_occurrences", "incomplete")
    )
    described = incomplete.describe()
    assert described.state == "unavailable" and "missing: occurrence_id" not in (
        described.detail or ""
    )
    assert "scientific_name" in (described.detail or "")


def test_bbox_filters_and_null_island(repo: PostgresOccurrenceRepository) -> None:
    world = OccurrenceQuery(bbox=BBox.world(), zoom=12, mode="points")
    ids = [r.occurrence_id for r in repo.fetch(world, after_id=None, max_rows=100)]
    assert ids == ["o1", "o2", "o3", "o4", "o6"]  # 0,0 excluded
    assert repo.count(world, cap=100) == (5, True)
    assert repo.count(world, cap=3) == (3, False)


def test_antimeridian_viewport(repo: PostgresOccurrenceRepository) -> None:
    pacific = OccurrenceQuery(bbox=BBox(170, -30, -170, -10), zoom=12)
    assert [
        r.occurrence_id for r in repo.fetch(pacific, after_id=None, max_rows=10)
    ] == ["o3", "o4"]


def test_taxon_time_month_filters_and_keyset(
    repo: PostgresOccurrenceRepository,
) -> None:
    q = OccurrenceQuery(bbox=BBox.world(), zoom=12, taxon_id="t1", year_from=1950)
    assert [r.occurrence_id for r in repo.fetch(q, after_id=None, max_rows=10)] == [
        "o2"
    ]
    months = OccurrenceQuery(bbox=BBox.world(), zoom=12, months=(9,))
    assert [
        r.occurrence_id for r in repo.fetch(months, after_id="o3", max_rows=10)
    ] == ["o4"]


def test_server_side_aggregation_whole_degree_only(
    repo: PostgresOccurrenceRepository,
) -> None:
    q = OccurrenceQuery(bbox=BBox.world(), zoom=1)
    assert repo.aggregate(q, cell_deg=0.5) is None
    cells = repo.aggregate(q, cell_deg=10.0)
    assert cells is not None
    assert sum(c.count for c in cells) == 5
    dracula = next(c for c in cells if c.top_genera and c.top_genera[0] == "Dracula")
    assert dracula.count == 2 and dracula.taxon_count == 1 and dracula.year_min == 1890


def test_service_end_to_end_protects_locality(
    repo: PostgresOccurrenceRepository,
) -> None:
    service = OccurrenceService(repo)
    response = service.query(OccurrenceQuery(bbox=BBox(-80, -5, -78, -3), zoom=10))
    assert response.mode == "points"
    protected = next(p for p in response.points if p.occurrenceID == "o1")
    assert (protected.decimalLatitude, protected.decimalLongitude) == (-3.5, -79.5)
    assert protected.locality is None
    unresolved = service.query(
        OccurrenceQuery(bbox=BBox(-1, 51, 1, 52), zoom=10)
    ).points[0]
    assert (
        unresolved.generalisationReason == "unresolved-assessment"
        and unresolved.locality is None
    )
