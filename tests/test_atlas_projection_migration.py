"""The proposed Atlas projection, applied to a reproduction of the production source.

Opt-in: set ATLAS_TEST_DATABASE_URL to a disposable PostgreSQL server. Each test
creates and drops its own database. public.orchid_occurrence is built from the
exact column list recorded by the read-only production diagnostic in
docs/evidence/audit-measurement-002/integration-gap-diagnostic.json, so the
migration is exercised against the real column layout, never production data.

All coordinates below are SYNTHETIC open-ocean points.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.atlas_intelligence.occurrences import (
    BBox,
    OccurrenceQuery,
    OccurrenceService,
    PostgresOccurrenceRepository,
)
from scripts.diagnose_atlas_occurrence_projection import diagnose

ROOT = Path(__file__).resolve().parents[1]
DSN = os.getenv("ATLAS_TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not DSN, reason="ATLAS_TEST_DATABASE_URL not set")

MIGRATION = (
    ROOT / "docs" / "atlas-explorer" / "20261011_atlas_public_occurrences_v1.sql"
)
ROLLBACK = (
    ROOT
    / "docs"
    / "atlas-explorer"
    / "20261011_atlas_public_occurrences_v1_rollback.sql"
)
PRODUCTION_COLUMNS = json.loads(
    (
        ROOT
        / "docs"
        / "evidence"
        / "audit-measurement-002"
        / "integration-gap-diagnostic.json"
    ).read_text()
)["occurrence_candidates"]["public.orchid_occurrence"]["columns"]

# occurrence_id, taxonomy_id, canonical_name_clean, lat, lng, raw_payload, gbif key
SOURCE_ROWS: list[tuple[Any, ...]] = [
    (
        1,
        10,
        "Dracula vampira",
        -30.25,
        -20.5,
        {
            "family": "Orchidaceae",
            "license": "CC-BY-4.0",
            "coordinateUncertaintyInMeters": "250",
            "basisOfRecord": "PreservedSpecimen",
            "countryCode": "EC",
            "datasetName": "Herbarium fixture",
        },
        111,
    ),
    (2, 10, "Dracula vampira", -30.75, -20.25, {}, None),
    (3, 20, "Hypoxis decumbens", -30.5, -20.75, {"family": "Hypoxidaceae"}, None),
    (4, None, "Dracula vampira", -30.25, -20.25, {"family": "Orchidaceae"}, None),
    (5, 10, "Dracula vampira", 0.0, 0.0, {"family": "Orchidaceae"}, None),
    (
        6,
        10,
        "Dracula vampira",
        -30.5,
        -20.5,
        {"coordinateUncertaintyInMeters": "about 1 km"},
        None,
    ),
]


@pytest.fixture()
def db() -> Iterator[Any]:
    psycopg = pytest.importorskip("psycopg")
    from psycopg import conninfo
    from psycopg.rows import dict_row

    name = f"atlas_proj_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    dsn = conninfo.make_conninfo(DSN, dbname=name)

    def db_execute(callback: Any) -> Any:
        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                result = callback(cur)
            conn.commit()
            return result

    columns = ", ".join(
        f'"{column}" {kind}' for column, kind in PRODUCTION_COLUMNS.items()
    )

    def setup(cur: Any) -> None:
        cur.execute(
            "CREATE TABLE public.orchid_taxonomy (id bigint PRIMARY KEY, scientific_name text, genus text)"
        )
        cur.execute(
            "INSERT INTO public.orchid_taxonomy VALUES (10, 'Dracula vampira (Luer) Luer', 'Dracula'),"
            " (20, 'Hypoxis decumbens L.', 'Hypoxis')"
        )
        cur.execute(f"CREATE TABLE public.orchid_occurrence ({columns})")
        for oid, tax, name, lat, lng, payload, gbif in SOURCE_ROWS:
            cur.execute(
                """INSERT INTO public.orchid_occurrence
                   (occurrence_id, taxonomy_id, canonical_name_clean, scientific_name, decimal_latitude,
                    decimal_longitude, raw_payload, canonical_gbif_occurrence_key, source_table,
                    source_record_id, event_year, event_month, locality)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,'records',%s,2001,3,'Fixture locality')""",
                (oid, tax, name, name, lat, lng, json.dumps(payload), gbif, oid * 100),
            )

    db_execute(setup)
    try:
        yield db_execute
    finally:
        with psycopg.connect(DSN, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def _apply(db: Any, path: Path) -> None:
    db(lambda cur: cur.execute(path.read_text()))


def test_projection_satisfies_the_contract_and_scopes_to_orchidaceae(db: Any) -> None:
    _apply(db, MIGRATION)
    repo = PostgresOccurrenceRepository(db, "oc_atlas.public_occurrences_v1")
    assert repo.describe().state == "available"

    rows = db(
        lambda cur: (
            cur.execute(
                "SELECT occurrence_id, family, family_basis, coordinate_uncertainty_in_meters, license,"
                " country_code, references_uri, assessment_resolved, genus, scientific_name"
                " FROM oc_atlas.public_occurrences_v1 ORDER BY occurrence_id"
            ),
            cur.fetchall(),
        )[1]
    )
    by_id = {r["occurrence_id"]: r for r in rows}
    # Unlinked (4) and null-island (5) rows never enter the projection.
    assert sorted(by_id) == ["1", "2", "3", "6"]
    assert (
        by_id["1"]["family_basis"] == "source_stated"
        and by_id["1"]["license"] == "CC-BY-4.0"
    )
    assert (
        by_id["1"]["coordinate_uncertainty_in_meters"] == 250.0
        and by_id["1"]["country_code"] == "EC"
    )
    assert by_id["1"]["references_uri"] == "https://www.gbif.org/occurrence/111"
    assert (
        by_id["2"]["family"] == "Orchidaceae"
        and by_id["2"]["family_basis"] == "orchid_backbone_link"
    )
    assert by_id["3"]["family"] == "Hypoxidaceae"
    assert (
        by_id["6"]["coordinate_uncertainty_in_meters"] is None
    )  # unparseable value is not guessed
    assert all(r["assessment_resolved"] is False for r in rows)
    assert (
        by_id["1"]["scientific_name"] == "Dracula vampira"
        and by_id["1"]["genus"] == "Dracula"
    )

    service = OccurrenceService(repo)
    served = service.query(
        OccurrenceQuery(bbox=BBox(-21, -31, -20, -30), zoom=12, mode="points")
    ).points
    assert sorted(p.occurrenceID for p in served) == ["1", "2", "6"]  # Hypoxis excluded
    for point in served:
        assert point.generalised and point.generalisationReason in {
            "unresolved-assessment",
            "coordinate-uncertainty",
        }
        assert point.locality is None and point.references is None


def test_migration_fails_closed_when_the_source_lacks_a_column(db: Any) -> None:
    db(
        lambda cur: cur.execute(
            "ALTER TABLE public.orchid_occurrence DROP COLUMN raw_payload"
        )
    )
    with pytest.raises(Exception, match="precondition"):
        _apply(db, MIGRATION)
    exists = db(
        lambda cur: (
            cur.execute("SELECT to_regclass('oc_atlas.public_occurrences_v1') AS r"),
            cur.fetchone(),
        )[1]
    )
    assert exists["r"] is None


def test_migration_is_reapplicable_and_rolls_back(db: Any) -> None:
    _apply(db, MIGRATION)
    _apply(db, MIGRATION)
    _apply(db, ROLLBACK)
    exists = db(
        lambda cur: (
            cur.execute("SELECT to_regclass('oc_atlas.public_occurrences_v1') AS r"),
            cur.fetchone(),
        )[1]
    )
    assert exists["r"] is None
    remaining = db(
        lambda cur: (
            cur.execute("SELECT count(*) AS n FROM public.orchid_occurrence"),
            cur.fetchone(),
        )[1]
    )
    assert remaining["n"] == len(SOURCE_ROWS)  # the source is never modified


def test_diagnostic_reports_counts_only(db: Any) -> None:
    report = db(diagnose)
    verdict = report["verdict"]
    assert verdict["projection_possible"] is True
    assert verdict["projectable_rows"] == 4
    assert verdict["rows_excluded_as_non_orchid"] == 1
    assert verdict["rows_relying_on_backbone_for_family"] == 2
    assert verdict["licence_stated_rows"] == 1
    assert report["genera_stating_non_orchid_family"] == [
        {"genus": "Hypoxis", "stated_family": "Hypoxidaceae", "n": 1}
    ]
    text = json.dumps(report, default=str)
    for _, _, _, lat, lng, _, _ in SOURCE_ROWS:
        if (lat, lng) != (0.0, 0.0):
            assert not re.search(rf"(?<![\d.]){re.escape(str(lat))}(?!\d)", text)
            assert not re.search(rf"(?<![\d.]){re.escape(str(lng))}(?!\d)", text)
    assert "Fixture locality" not in text
