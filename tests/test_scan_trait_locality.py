"""Read-only trait-table locality scanner (scripts/scan_trait_locality.py).

Runs against a throwaway database on the disposable test server
(TEST_DATABASE_URL, then DATABASE_URL); ``requires_postgres`` skips off-runner
and fails in CI when that server is unusable. Every planted row below is a
SYNTHETIC shape written for this test (fictional place names, made-up grid
references and coordinates); none is real locality data. The database is
dropped afterwards.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from tests.evidence_feedback_stores import test_database_url

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scan_trait_locality.py"

DMS = "12°34'56\"S 77°01'02\"W"
UTM = "17N 630084 4833438"
PLUS_CODE = "849VCWC8+R9"
MGRS_LOWER = "33twn1234567890"
DECIMAL_PAIR = "9.12 -83.65"
TYPE_LOCALITY_VALUE = "Cerro Fixtura synthetic"
COLLECTION_SITE_VALUE = "Finca Fixtura"
TYPE_LOCALITY_LABEL = "type locality Volcan Barutown"
COLLECTED_LABEL = "collected near Montefixture ridge"
COLLECTOR_LABEL = "Collector: J. Fixturesen 4417"
ELEV_RAW = "2351 m"
ELEV_KEY = "verbatimElevationFixture"
LAT, LON = "9.736512", "-83.917734"
PLANTED = (
    DMS,
    "12°34",
    "630084",
    "4833438",
    PLUS_CODE,
    "849VCWC8",
    MGRS_LOWER,
    "33twn",
    DECIMAL_PAIR,
    "83.65",
    TYPE_LOCALITY_VALUE,
    "Cerro",
    COLLECTION_SITE_VALUE,
    "Finca",
    TYPE_LOCALITY_LABEL,
    "Volcan",
    "Barutown",
    COLLECTED_LABEL,
    "Montefixture",
    COLLECTOR_LABEL,
    "Fixturesen",
    "4417",
    ELEV_RAW,
    "2351",
    ELEV_KEY,
    LAT,
    LON,
    "9.7365",
    "83.9177",
)
LABELS = (TYPE_LOCALITY_LABEL, COLLECTED_LABEL, COLLECTOR_LABEL, "type locality")
CLEAN_TRAITS = (
    ("t5", "tx3", "flower_color", "yellow", None, "synthetic fixture", ["golden"]),
    ("t6", "tx3", "labellum_length", "12 mm", "mm", "synthetic fixture", None),
    ("t7", "tx4", "growth_habit", "epiphytic", None, "synthetic fixture", ["epiphyte"]),
    ("t8", "tx4", "chromosome_count", "2n = 40", None, "synthetic fixture", None),
    ("t9", "tx4", "petal_width_range", "12.5 13.2", "mm", "synthetic fixture", None),
)
TRAITS_DDL = (
    "CREATE TABLE oc_traits.traits(trait_id text PRIMARY KEY, taxon_id text, "
    "trait_name text, trait_value text, unit text, source_name text, aliases text[])"
)
RESOLVED_DDL = (
    (
        "CREATE TABLE oc_fixture.resolved(taxon_id text, predicate text, object text, "
        "confidence_score numeric, point_a double precision, point_b numeric)"
    ),
    "CREATE VIEW oc_views.trait_resolved_v4 AS SELECT * FROM oc_fixture.resolved",
)
# public.record_traits as in record_traits_schema.txt (trigger omitted).
RECORD_TRAITS_DDL = """
CREATE TABLE public.record_traits(
    record_id text PRIMARY KEY, source text NOT NULL,
    elev_m numeric, elev_min_m numeric, elev_max_m numeric,
    elev_raw_key text, elev_raw_value text, elev_parse_method text,
    elev_flag_invalid boolean NOT NULL DEFAULT false,
    elev_flag_outlier boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    elev_m_valid numeric
)
"""
INSERT_TRAIT = "INSERT INTO oc_traits.traits VALUES (%s, %s, %s, %s, %s, %s, %s)"
INSERT_RESOLVED = "INSERT INTO oc_fixture.resolved VALUES (%s, %s, %s, %s, %s, %s)"


def _load():
    spec = importlib.util.spec_from_file_location("scan_trait_locality", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dsn(base: str, **overrides: str) -> str:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = conninfo_to_dict(base)
    params.update(overrides)
    return make_conninfo(**params)


@pytest.fixture
def database():
    import psycopg
    from psycopg import sql

    admin = test_database_url()
    name = f"oc_trait_scan_{secrets.token_hex(4)}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = _dsn(admin, dbname=name)
    with psycopg.connect(dsn, autocommit=True) as conn:
        for schema in ("oc_traits", "oc_views", "oc_fixture"):
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(TRAITS_DDL)
        for statement in RESOLVED_DDL:
            conn.execute(statement)
    try:
        yield dsn
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )


def insert_clean(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.cursor().executemany(INSERT_TRAIT, CLEAN_TRAITS)
        conn.cursor().executemany(
            INSERT_RESOLVED,
            [
                ("tx3", "flower_color", "white", 0.9, 0.25, 0.5),
                ("tx3", "petal_ratio", "narrow", 0.8512, 0.1234, 0.5678),
            ],
        )


def insert_planted(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        cur = conn.cursor()
        cur.executemany(
            INSERT_TRAIT,
            [
                (
                    "t1",
                    "tx1",
                    "type locality",
                    TYPE_LOCALITY_VALUE,
                    None,
                    "fixture",
                    None,
                ),
                ("t2", "tx1", "holotype_coordinates", DMS, None, "fixture", None),
                ("t3", "tx2", "collection_note", UTM, None, "fixture", None),
                ("t4", "tx2", "habitat_code", PLUS_CODE, None, "fixture", None),
                ("t10", "tx2", "grid_note", MGRS_LOWER, None, "fixture", None),
                (
                    "t11",
                    "tx2",
                    "flower_color",
                    "red",
                    None,
                    "fixture",
                    ["red", DECIMAL_PAIR],
                ),
                ("t12", "tx5", TYPE_LOCALITY_LABEL, "yes", None, "fixture", None),
                ("t13", "tx5", COLLECTED_LABEL, "yes", None, "fixture", None),
            ],
        )
        cur.executemany(
            INSERT_RESOLVED,
            [
                ("tx1", "collection site", COLLECTION_SITE_VALUE, 0.7, None, None),
                ("tx2", "elevation", ELEV_RAW, 0.6, None, None),
                ("tx4", COLLECTOR_LABEL, "x", 0.5, None, None),
                ("tx6", "habit", "terrestrial", 0.5, float(LAT), LON),
            ],
        )
        conn.execute(RECORD_TRAITS_DDL)
        cur.executemany(
            "INSERT INTO public.record_traits(record_id, source, elev_m, elev_raw_key, "
            "elev_raw_value) VALUES (%s, %s, %s, %s, %s)",
            [
                ("r1", "synthetic", 2351, ELEV_KEY, ELEV_RAW),
                ("r2", "synthetic", None, None, None),
            ],
        )


def run_scan(dsn: str, *args: str) -> tuple[int, dict, str]:
    env = {**os.environ, "OC_SCAN_DSN": dsn}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--database-url-env", "OC_SCAN_DSN", *args],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return result.returncode, json.loads(result.stdout), result.stdout + result.stderr


def by_source(report: dict) -> dict[str, dict]:
    return {item["source"]: item for item in report["sources"]}


def assert_no_planted_text(output: str) -> None:
    lowered = output.lower()
    for value in (*PLANTED, *LABELS):
        assert value not in output, value
        assert value.lower() not in lowered, value
        assert json.dumps(value)[1:-1] not in output, value


def reported_words(report: dict) -> set[str]:
    """Every string in the report outside the fixed limitations text."""
    words: set[str] = set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key != "limitations":
                    words.add(key)
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            words.add(value)

    walk(report)
    return words


@pytest.mark.requires_postgres
def test_planted_locality_is_flagged_and_no_text_is_printed(database):
    insert_clean(database)
    insert_planted(database)
    code, report, output = run_scan(database)
    assert code == 1, output
    assert report["status"] == "FLAGGED"
    assert report["values_included"] is False
    assert report["labels_included"] is False
    sources = by_source(report)

    traits = sources["oc_traits.traits"]
    assert traits["sampled_rows"] == 13
    # t1-t4, t10-t13 are planted; the five clean rows (incl. "2n = 40" and
    # "12.5 13.2") pass.
    assert traits["rows_flagged"] == 8
    assert traits["value_hits"] == {
        "coordinate_value": {
            "rows": 5,  # DMS, UTM, plus code, lower-case MGRS, decimal pair in text[]
            "columns": ["aliases", "trait_value"],
        }
    }
    assert traits["label_hits"] == {
        "collection_site_label": {"rows": 1, "columns": ["trait_name"]},
        "coordinate_label": {"rows": 1, "columns": ["trait_name"]},
        "type_locality_label": {"rows": 2, "columns": ["trait_name"]},
    }
    assert traits["flagged_columns"] == []

    resolved = sources["oc_views.trait_resolved_v4"]
    assert resolved["sampled_rows"] == 6
    assert resolved["rows_flagged"] == 4
    assert resolved["label_hits"] == {
        "collection_site_label": {
            "rows": 2,
            "columns": ["predicate"],
        },  # site + collector
        "elevation_label": {"rows": 1, "columns": ["predicate"]},
    }
    assert resolved["possible_coordinate_pairs"] == [
        {
            "category": "possible_coordinate_pair",
            "columns": ["point_a", "point_b"],
            "rows": 1,
        }
    ]

    record = sources["public.record_traits"]
    assert record["rows_flagged"] == 1
    flagged = {c["column"]: c for c in record["flagged_columns"]}
    assert flagged["elev_m"]["non_null_in_sample"] == 1
    assert flagged["elev_raw_value"]["non_null_in_sample"] == 1
    assert flagged["elev_m"]["category"] == "elevation_column"
    assert "elev_flag_invalid" not in flagged

    assert_no_planted_text(output)


@pytest.mark.requires_postgres
def test_report_uses_only_fixed_vocabulary_and_column_names(database):
    insert_clean(database)
    insert_planted(database)
    _, report, _ = run_scan(database)
    module = _load()
    column_names = {
        "trait_id", "taxon_id", "trait_name", "trait_value", "unit", "source_name",
        "aliases", "predicate", "object", "confidence_score", "point_a", "point_b",
        "record_id", "source", "elev_m", "elev_min_m", "elev_max_m", "elev_raw_key",
        "elev_raw_value", "elev_parse_method", "elev_m_valid",
    }  # fmt: skip
    structure = {
        "status", "FLAGGED", "read_only", "sample_limit", "rows_flagged", "sources",
        "values_included", "labels_included", "source", "present", "sampled_rows",
        "columns_scanned", "flagged_columns", "value_hits", "label_hits",
        "possible_coordinate_pairs", "column", "category", "non_null_in_sample",
        "rows", "columns", "oc_views.trait_resolved_v4", "oc_traits.traits",
        "public.record_traits",
    }  # fmt: skip
    unexpected = reported_words(report) - column_names - structure - module.CATEGORIES
    assert not unexpected, unexpected
    assert report["limitations"] == list(module.LIMITATIONS)


@pytest.mark.requires_postgres
def test_clean_rows_pass(database):
    insert_clean(database)
    code, report, output = run_scan(database)
    assert code == 0, output
    assert report["status"] == "CLEAN"
    assert report["rows_flagged"] == 0
    sources = by_source(report)
    assert sources["public.record_traits"] == {
        "source": "public.record_traits",
        "present": False,
    }
    for name in ("oc_traits.traits", "oc_views.trait_resolved_v4"):
        assert sources[name]["rows_flagged"] == 0
        assert sources[name]["value_hits"] == {}
        assert sources[name]["label_hits"] == {}
        assert sources[name]["possible_coordinate_pairs"] == []


@pytest.mark.requires_postgres
def test_sampling_is_bounded_by_limit(database):
    import psycopg

    with psycopg.connect(database, autocommit=True) as conn:
        conn.cursor().executemany(
            "INSERT INTO oc_traits.traits VALUES (%s, 'tx', 'flower_color', 'red', NULL, NULL, NULL)",
            [(f"c{i}",) for i in range(30)],
        )
    _, report, _ = run_scan(database, "--limit", "5")
    assert report["sample_limit"] == 5
    assert by_source(report)["oc_traits.traits"]["sampled_rows"] == 5


@pytest.mark.requires_postgres
def test_scan_runs_in_a_read_only_transaction(database, monkeypatch):
    import psycopg

    module = _load()
    insert_clean(database)
    observed = []

    def spying(cur, source, limit):
        observed.append(cur.execute("SHOW transaction_read_only").fetchone()[0])
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            cur.execute("CREATE TEMP TABLE scanner_write_probe(x int)")
        raise RuntimeError("probe complete")  # the transaction is aborted now

    monkeypatch.setattr(module, "scan_source", spying)
    # The connection is NOT read-only here: scan() must make its own transaction so.
    with (
        psycopg.connect(database) as conn,
        pytest.raises(RuntimeError, match="probe complete"),
    ):
        module.scan(conn)
    assert observed == ["on"]


def test_flagging_is_decided_by_the_member_view_screens():
    module = _load()
    from app import matrix_member_views

    for text in (DMS, UTM, PLUS_CODE, "type locality", "collection site", "elev_m"):
        assert module.screen_categories(text), text
        assert matrix_member_views.screened_text(text) == matrix_member_views.WITHHELD
    for text in (
        "yellow",
        "12 mm",
        "epiphytic",
        "flower_color",
        "2n = 40",
        "12.5 13.2",
    ):
        assert module.screen_categories(text) == [], text
        assert matrix_member_views.screened_text(text) == text
    # Scanner-side folds, reported as limitations of the reused screen. The member
    # screen withholds lower-case MGRS itself since #1708; the scanner's fold is kept
    # and still reports it.
    assert matrix_member_views.screened_text(MGRS_LOWER) == matrix_member_views.WITHHELD
    assert matrix_member_views.screened_text(DECIMAL_PAIR) == DECIMAL_PAIR
    for text in (MGRS_LOWER, DECIMAL_PAIR):
        assert module.screen_categories(text) == ["coordinates"], text
    source = SCRIPT.read_text(encoding="utf-8")
    # No locality screen of its own: the only local patterns are the two folds
    # and the four category-naming patterns.
    assert len(re.findall(r"re\.compile\(", source)) == 5


def test_unavailable_database_is_reported_without_the_connection_string():
    secret = f"pw-{secrets.token_hex(8)}"
    env = {
        **os.environ,
        "OC_SCAN_DSN": f"postgresql://someone:{secret}@127.0.0.1:1/nowhere?connect_timeout=2",
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--database-url-env", "OC_SCAN_DSN"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "UNAVAILABLE"
    assert secret not in result.stdout + result.stderr
