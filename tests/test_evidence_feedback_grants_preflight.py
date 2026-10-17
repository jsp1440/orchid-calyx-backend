"""EVIDENCE-FEEDBACK-001 migration parity and the read-only grants preflight.

The parity test needs no database. The rest run against a throwaway database
and a throwaway low-privilege role created on the disposable test server
(TEST_DATABASE_URL, then DATABASE_URL); ``requires_postgres`` skips off-runner
and fails in CI when that server is unusable. Both are dropped afterwards.
Nothing here is ever pointed at production.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

from app.evidence_feedback import EvidenceFeedbackService, FeedbackClass, ObjectType
from app.evidence_feedback.postgres_repository import (
    SCHEMA,
    SCHEMA_STATEMENTS,
    TABLES,
    PostgresEvidenceFeedbackRepository,
)
from app.evidence_feedback.repository import EvidenceFeedbackStoreUnavailable
from tests.evidence_feedback_stores import test_database_url

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "EVIDENCE-FEEDBACK-001.sql"
SCRIPT = ROOT / "scripts" / "preflight_evidence_feedback_grants.py"
CLOCK = "2026-09-30T12:00:00+00:00"


def _normalize(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().rstrip(";").strip()


def migration_statements() -> list[str]:
    """Executable statements of the migration, comments and BEGIN/COMMIT removed."""

    lines = [
        line
        for line in MIGRATION.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("--")
    ]
    statements = [_normalize(part) for part in "\n".join(lines).split(";")]
    return [s for s in statements if s and s.upper() not in {"BEGIN", "COMMIT"}]


def grant_statements(role: str) -> list[str]:
    """The migration's commented GRANT block, with the role substituted."""

    grants = []
    for line in MIGRATION.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"-- (GRANT .+);", line.strip())
        if match:
            grants.append(match.group(1).replace(':"runtime_role"', f'"{role}"'))
    return grants


# --- parity (no database) ----------------------------------------------------------


def test_migration_matches_schema_statements_exactly():
    assert migration_statements() == [_normalize(s) for s in SCHEMA_STATEMENTS]


def test_migration_is_additive_and_idempotent_by_construction():
    text = MIGRATION.read_text(encoding="utf-8")
    for statement in migration_statements():
        assert re.match(r"CREATE (SCHEMA|TABLE|INDEX) IF NOT EXISTS ", statement), (
            statement
        )
    executable = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("--")
    )
    for forbidden in (
        "DROP",
        "TRUNCATE",
        "ALTER",
        "DELETE",
        "UPDATE ",
        "GRANT",
        "REVOKE",
    ):
        assert forbidden not in executable.upper(), forbidden


def test_commented_grants_cover_schema_tables_and_sequences():
    grants = grant_statements("rt")
    assert f'GRANT USAGE ON SCHEMA {SCHEMA} TO "rt"' in grants
    for table in TABLES:
        assert (
            f'GRANT SELECT, INSERT, UPDATE ON TABLE {SCHEMA}.{table} TO "rt"' in grants
        )
    assert f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO "rt"' in grants
    assert len(grants) == len(TABLES) + 2


# --- preflight against a disposable PostgreSQL ------------------------------------------


def _dsn(base: str, **overrides: str) -> str:
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    params = conninfo_to_dict(base)
    params.update(overrides)
    return make_conninfo(**params)


@pytest.fixture
def disposable():
    import psycopg
    from psycopg import sql

    admin = test_database_url()
    token = secrets.token_hex(4)
    database = f"oc_fb_grants_{token}"
    role = f"oc_fb_runtime_{token}"
    password = f"pw-{secrets.token_hex(8)}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        conn.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
    admin_db = _dsn(admin, dbname=database)
    with psycopg.connect(admin_db, autocommit=True) as conn:
        # PostgreSQL 15+ already denies CREATE on public to PUBLIC; make it explicit.
        conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        conn.execute(
            sql.SQL("REVOKE CREATE ON DATABASE {} FROM PUBLIC").format(
                sql.Identifier(database)
            )
        )
    try:
        yield {
            "admin": admin_db,
            "runtime": _dsn(admin, dbname=database, user=role, password=password),
            "role": role,
            "password": password,
        }
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(database)
                )
            )
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def run_preflight(dsn: str) -> tuple[int, dict, str]:
    env = {**os.environ, "OC_PREFLIGHT_DSN": dsn}
    env.pop("DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--database-url-env", "OC_PREFLIGHT_DSN"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result.returncode, json.loads(result.stdout), result.stdout + result.stderr


def apply_migration(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(MIGRATION.read_text(encoding="utf-8"))


def schema_exists(dsn: str) -> bool:
    import psycopg

    with psycopg.connect(dsn) as conn:
        return bool(
            conn.execute(
                "SELECT to_regnamespace(%s) IS NOT NULL", (SCHEMA,)
            ).fetchone()[0]
        )


@pytest.mark.requires_postgres
def test_preflight_reports_absent_objects_and_performs_no_ddl(disposable):
    code, report, _ = run_preflight(disposable["admin"])
    assert code == 1
    assert report["status"] == "MISSING"
    assert report["schema"] == {"name": SCHEMA, "present": False, "usage": False}
    assert f"SCHEMA {SCHEMA}" in report["missing"]
    assert all(not t["present"] for t in report["tables"])
    assert report["ddl_performed"] is False
    # The admin role could have created the schema; the preflight did not.
    assert report["role_can_create_schema"] is True
    assert not schema_exists(disposable["admin"])


@pytest.mark.requires_postgres
def test_low_privilege_role_reports_missing_grants_then_ok_after_granting(disposable):
    import psycopg

    apply_migration(disposable["admin"])
    apply_migration(disposable["admin"])  # idempotent: a second run is a no-op

    code, report, output = run_preflight(disposable["runtime"])
    assert code == 1, output
    assert report["status"] == "MISSING"
    assert report["role"] == disposable["role"]
    assert report["role_can_create_schema"] is False
    assert f"USAGE ON SCHEMA {SCHEMA}" in report["missing"]
    for table in TABLES:
        for privilege in ("SELECT", "INSERT", "UPDATE"):
            assert f"{privilege} ON TABLE {SCHEMA}.{table}" in report["missing"]
    assert f"USAGE ON SEQUENCE {SCHEMA}.case_events_event_id_seq" in report["missing"]
    assert not any(
        m.startswith(("TABLE ", "INDEX ", "SCHEMA ")) for m in report["missing"]
    )
    assert disposable["password"] not in output

    # Without the grants the runtime store really is unusable for this role.
    with pytest.raises(EvidenceFeedbackStoreUnavailable):
        _submit(PostgresEvidenceFeedbackRepository(disposable["runtime"]))

    with psycopg.connect(disposable["admin"], autocommit=True) as conn:
        for grant in grant_statements(disposable["role"]):
            conn.execute(grant)

    code, report, output = run_preflight(disposable["runtime"])
    assert code == 0, output
    assert report["status"] == "OK"
    assert report["missing"] == []
    assert report["schema"]["usage"] is True
    assert all(all(t["privileges"].values()) for t in report["tables"])
    assert report["sequences"] == [
        {"name": f"{SCHEMA}.case_events_event_id_seq", "present": True, "usage": True}
    ]
    assert disposable["password"] not in output

    # And the granted set is sufficient: the runtime role can use the store.
    _submit(PostgresEvidenceFeedbackRepository(disposable["runtime"]))


@pytest.mark.requires_postgres
def test_partial_grants_name_exactly_what_is_missing(disposable):
    import psycopg
    from psycopg import sql

    apply_migration(disposable["admin"])
    role = sql.Identifier(disposable["role"])
    with psycopg.connect(disposable["admin"], autocommit=True) as conn:
        conn.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                sql.Identifier(SCHEMA), role
            )
        )
        for table in TABLES:
            conn.execute(
                sql.SQL("GRANT SELECT ON TABLE {}.{} TO {}").format(
                    sql.Identifier(SCHEMA), sql.Identifier(table), role
                )
            )
    code, report, _ = run_preflight(disposable["runtime"])
    assert code == 1
    expected = [
        f"{privilege} ON TABLE {SCHEMA}.{table}"
        for table in TABLES
        for privilege in ("INSERT", "UPDATE")
    ] + [f"USAGE ON SEQUENCE {SCHEMA}.case_events_event_id_seq"]
    assert report["missing"] == expected


def test_preflight_without_a_connection_string_is_unavailable():
    env = {k: v for k, v in os.environ.items() if k != "OC_PREFLIGHT_DSN"}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--database-url-env", "OC_PREFLIGHT_DSN"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "UNAVAILABLE"


def test_preflight_never_prints_an_unreachable_connection_string():
    secret = f"pw-{secrets.token_hex(8)}"
    dsn = f"postgresql://someone:{secret}@127.0.0.1:1/nowhere?connect_timeout=2"
    env = {**os.environ, "OC_PREFLIGHT_DSN": dsn}
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--database-url-env", "OC_PREFLIGHT_DSN"],
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
    assert "someone" not in result.stdout + result.stderr


@pytest.mark.requires_postgres
def test_an_object_of_the_wrong_kind_is_not_reported_ok(disposable):
    import psycopg

    apply_migration(disposable["admin"])
    with psycopg.connect(disposable["admin"], autocommit=True) as conn:
        conn.execute(f"ALTER TABLE {SCHEMA}.case_events RENAME TO case_events_real")
        conn.execute(
            f"CREATE VIEW {SCHEMA}.case_events AS SELECT * FROM {SCHEMA}.case_events_real"
        )
    code, report, output = run_preflight(disposable["admin"])
    assert code == 1, output
    assert report["status"] == "MISSING"
    assert f"TABLE {SCHEMA}.case_events (found a view)" in report["missing"]
    entry = {t["name"]: t for t in report["tables"]}[f"{SCHEMA}.case_events"]
    assert entry["present"] is False
    assert entry["found_kind"] == "view"


@pytest.mark.requires_postgres
def test_sql_ascii_database_reports_text_not_bytes():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict

    admin = test_database_url()
    name = f"oc_fb_ascii_{secrets.token_hex(4)}"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(
            sql.SQL(
                "CREATE DATABASE {} ENCODING 'SQL_ASCII' TEMPLATE template0 "
                "LC_COLLATE 'C' LC_CTYPE 'C'"
            ).format(sql.Identifier(name))
        )
    try:
        dsn = _dsn(admin, dbname=name)
        apply_migration(dsn)
        code, report, output = run_preflight(dsn)
        assert code == 0, output
        assert report["status"] == "OK"
        assert report["role"] == conninfo_to_dict(admin)["user"]
        assert report["sequences"][0]["name"] == f"{SCHEMA}.case_events_event_id_seq"
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(name)
                )
            )


def _submit(repository) -> None:
    service = EvidenceFeedbackService(repository, clock=lambda: CLOCK)
    version = service.register_object(
        object_id="lexicon:labellum",
        object_type=ObjectType.LEXICON,
        payload={"term": "labellum", "definition": "a modified petel"},
    )
    service.submit(
        object_id=version.object_id,
        object_version_hash=version.version_hash,
        object_type=ObjectType.LEXICON,
        page_context="/lexicon/labellum",
        feedback_class=FeedbackClass.REPORT_PROBLEM,
        statement="Petal is misspelled.",
        submitter_id="member-1",
    )
