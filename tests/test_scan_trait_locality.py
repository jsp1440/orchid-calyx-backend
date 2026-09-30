"""Read-only trait-table locality scanner (scripts/scan_trait_locality.py).

Runs against a throwaway database on the disposable test server
(TEST_DATABASE_URL, then DATABASE_URL); ``requires_postgres`` skips off-runner
and fails in CI when that server is unusable. Every planted row below is a
SYNTHETIC shape written for this test (fictional place names, made-up grid
references); none is real locality data. The database is dropped afterwards.
"""

from __future__ import annotations

import importlib.util
import json
import os
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
TYPE_LOCALITY_VALUE = "Cerro Fixtura synthetic"
COLLECTION_SITE_VALUE = "Finca Fixtura"
COLLECTOR_LABEL = "Collector: J. Fixturesen 4417"
ELEV_RAW = "2351 m"
ELEV_KEY = "verbatimElevationFixture"
PLANTED = (
    DMS,
    "12°34",
    "630084",
    "4833438",
    PLUS_CODE,
    "849VCWC8",
    TYPE_LOCALITY_VALUE,
    "Cerro",
    COLLECTION_SITE_VALUE,
    "Finca",
    COLLECTOR_LABEL,
    "Fixturesen",
    "4417",
    ELEV_RAW,
    "2351",
    ELEV_KEY,
)
CLEAN_TRAITS = (
    ("t5", "tx3", "flower_color", "yellow", None, "synthetic fixture"),
    ("t6", "tx3", "labellum_length", "12 mm", "mm", "synthetic fixture"),
    ("t7", "tx4", "growth_habit", "epiphytic", None, "synthetic fixture"),
)
TRAITS_DDL = (
    "CREATE TABLE oc_traits.traits(trait_id text PRIMARY KEY, taxon_id text, "
    "trait_name text, trait_value text, unit text, source_name text)"
)
RESOLVED_DDL = (
    (
        "CREATE TABLE oc_fixture.resolved(taxon_id text, predicate text, object text, "
        "confidence_score numeric)"
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
        conn.cursor().executemany(
            "INSERT INTO oc_traits.traits VALUES (%s, %s, %s, %s, %s, %s)", CLEAN_TRAITS
        )
        conn.execute(
            "INSERT INTO oc_fixture.resolved VALUES ('tx3', 'flower_color', 'white', 0.9)"
        )


def insert_planted(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        cur = conn.cursor()
        cur.executemany(
            "INSERT INTO oc_traits.traits VALUES (%s, %s, %s, %s, %s, %s)",
            [
                (
                    "t1",
                    "tx1",
                    "type locality",
                    TYPE_LOCALITY_VALUE,
                    None,
                    "synthetic fixture",
                ),
                ("t2", "tx1", "holotype_coordinates", DMS, None, "synthetic fixture"),
                ("t3", "tx2", "collection_note", UTM, None, "synthetic fixture"),
                ("t4", "tx2", "habitat_code", PLUS_CODE, None, "synthetic fixture"),
            ],
        )
        cur.executemany(
            "INSERT INTO oc_fixture.resolved VALUES (%s, %s, %s, %s)",
            [
                ("tx1", "collection site", COLLECTION_SITE_VALUE, 0.7),
                ("tx2", "elevation", ELEV_RAW, 0.6),
                ("tx4", COLLECTOR_LABEL, "x", 0.5),
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


def assert_no_planted_values(output: str) -> None:
    for value in PLANTED:
        assert value not in output, value
        assert json.dumps(value)[1:-1] not in output, value


@pytest.mark.requires_postgres
def test_planted_locality_is_flagged_and_never_printed(database):
    insert_clean(database)
    insert_planted(database)
    code, report, output = run_scan(database)
    assert code == 1, output
    assert report["status"] == "FLAGGED"
    assert report["read_only"] is True
    assert report["values_included"] is False
    sources = by_source(report)
    assert set(sources) == {
        "oc_views.trait_resolved_v4",
        "oc_traits.traits",
        "public.record_traits",
    }

    traits = sources["oc_traits.traits"]
    assert traits["sampled_rows"] == 7
    assert traits["rows_flagged"] == 4  # t1..t4; the three clean rows pass
    assert traits["value_hits"] == [
        {
            "column": "trait_value",
            "rows": 3,
            "matched": ["coordinates"],
        }  # DMS, UTM, plus code
    ]
    assert [(x["label"], x["rows"]) for x in traits["flagged_labels"]] == [
        ("holotype_coordinates", 1),
        ("type locality", 1),
    ]
    assert traits["withheld_labels"] == 0
    assert traits["flagged_columns"] == []

    resolved = sources["oc_views.trait_resolved_v4"]
    assert resolved["sampled_rows"] == 4
    assert resolved["rows_flagged"] == 3
    labels = {x["label"]: x for x in resolved["flagged_labels"]}
    assert set(labels) == {"collection site", "elevation"}
    assert labels["elevation"]["matched"] == ["sensitive_vocabulary"]
    assert resolved["withheld_labels"] == 1  # the collector label is counted, not shown

    record = sources["public.record_traits"]
    assert record["sampled_rows"] == 2
    assert record["rows_flagged"] == 1  # r2 has no elevation
    flagged = {c["column"]: c["non_null_in_sample"] for c in record["flagged_columns"]}
    assert flagged["elev_m"] == 1
    assert flagged["elev_raw_value"] == 1
    assert {"elev_min_m", "elev_max_m", "elev_m_valid"} <= set(flagged)
    assert "elev_flag_invalid" not in flagged  # booleans carry no elevation

    assert_no_planted_values(output)


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
        assert sources[name]["value_hits"] == []
        assert sources[name]["flagged_labels"] == []


@pytest.mark.requires_postgres
def test_sampling_is_bounded_by_limit(database):
    import psycopg

    with psycopg.connect(database, autocommit=True) as conn:
        conn.cursor().executemany(
            "INSERT INTO oc_traits.traits VALUES (%s, 'tx', 'flower_color', 'red', NULL, NULL)",
            [(f"c{i}",) for i in range(30)],
        )
    _, report, _ = run_scan(database, "--limit", "5")
    assert report["sample_limit"] == 5
    assert by_source(report)["oc_traits.traits"]["sampled_rows"] == 5


@pytest.mark.requires_postgres
def test_scan_runs_in_a_read_only_transaction(database, monkeypatch):
    import psycopg

    spec = importlib.util.spec_from_file_location("scan_trait_locality", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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


def test_screens_are_the_member_view_screens():
    spec = importlib.util.spec_from_file_location("scan_trait_locality", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from app import matrix_member_views

    for text in (DMS, UTM, PLUS_CODE, "type locality", "collection site", "elev_m"):
        assert module.screen_categories(text), text
        assert matrix_member_views.screened_text(text) == matrix_member_views.WITHHELD
    for text in ("yellow", "12 mm", "epiphytic", "flower_color", "labellum_length"):
        assert module.screen_categories(text) == [], text
        assert matrix_member_views.screened_text(text) == text
    # The scanner's only own pattern is the label print-shape; no locality regex.
    assert SCRIPT.read_text(encoding="utf-8").count("re.compile(") == 1


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
