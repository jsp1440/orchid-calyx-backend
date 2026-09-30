"""Gate 9: the acquisition-ledger schema migration and its fail-closed check.

``migrations/20260930_acquisition_ledger.sql`` is the only thing that creates
the ledger table outside the tests. These tests pin that it builds exactly the
schema the model needs on an empty database, upgrades the pre-#1697 table (no
``lease_token``) without losing or rewriting a row, and is a no-op when run
again; and that a missing or incompatible schema makes ZERO provider calls.

SQLite tests always run. Tests marked ``requires_postgres`` need a disposable
PostgreSQL (``TEST_DATABASE_URL``, then ``DATABASE_URL``; see
``tests/conftest.py``): they skip off-runner without one and fail in CI.
Everything here is provider-free; the provider is a spy that records calls.
"""

from __future__ import annotations

import importlib.util
import json
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import sessionmaker

from app.federation.firecrawl_mapper import build_source_profile
from app.federation.shared_firecrawl import SharedFirecrawlFederationService
from app.source_federation import acquisition_ledger_schema as schema_module
from app.source_federation.acquisition import AcquisitionRecord, AcquisitionRequest
from app.source_federation.acquisition_ledger import (
    AcquisitionLedger,
    LedgerSchemaUnavailableError,
)
from app.source_federation.acquisition_ledger_schema import (
    MIGRATION_PATH,
    apply_ledger_migration,
    ledger_schema_problems,
)
from app.source_federation.acquisition_models import AcquisitionLedgerRow
from tests.acquisition_ledger_backends import (
    disposable_postgres_schema,
    postgres_base_dsn,
    sqlite_memory_engine,
)

MODEL = AcquisitionLedgerRow.__table__
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
ROOT_URL = "https://powo.science.kew.org/"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise AssertionError("ledger schema tests must not open network connections")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)


# --- helpers -----------------------------------------------------------------


def _spy_mapper():
    mapper = Mock()
    mapper.map_source.return_value = build_source_profile(
        source_id="powo",
        root_url=ROOT_URL,
        urls=("https://powo.science.kew.org/taxon/test",),
    )
    return mapper


def _map(service, module="lexicon", search="Phragmipedium"):
    return service.map_source(
        consumer_module=module,
        source_id="powo",
        root_url=ROOT_URL,
        search=search,
        limit=25,
    )


def _legacy_table(
    metadata,
    *,
    drop=(),
    retype=None,
    not_null=(),
    unique=True,
):
    """The ledger table as an older model built it, with chosen defects.

    ``drop=("lease_token",)`` is the production-compatible pre-#1697 table:
    what ``create_all`` produced from the model before the fencing column.
    """
    columns = []
    for column in MODEL.columns:
        if column.name in drop:
            continue
        copy = column._copy()
        if retype and column.name in retype:
            copy = Column(column.name, retype[column.name], nullable=column.nullable)
        if column.name in not_null:
            copy.nullable = False
        columns.append(copy)
    extra = [UniqueConstraint("resource_key", name="uq_acquisition_resource_key")]
    return Table(MODEL.name, metadata, *columns, *(extra if unique else []))


def _assert_fails_closed(engine, expected_problem):
    """Both ledger and service refuse before any provider call."""
    session = sessionmaker(bind=engine)()
    with pytest.raises(LedgerSchemaUnavailableError) as excinfo:
        AcquisitionLedger(session).claim(
            AcquisitionRequest(
                url="https://example.org/x", provider="powo", consumer_module="m"
            ),
            worker_id="w",
        )
    assert expected_problem in excinfo.value.problems
    assert excinfo.value.code == "ledger_schema_unavailable"
    mapper = _spy_mapper()
    with pytest.raises(LedgerSchemaUnavailableError):
        _map(
            SharedFirecrawlFederationService(sessionmaker(bind=engine)(), mapper=mapper)
        )
    assert mapper.map_source.call_count == 0
    session.close()
    return excinfo.value


# --- SQLite: the check and the zero-call refusal -----------------------------


def test_model_built_sqlite_schema_passes_the_check():
    engine = sqlite_memory_engine()
    with engine.connect() as connection:
        assert ledger_schema_problems(connection) == ()


def test_sqlite_missing_table_makes_zero_provider_calls():
    engine = create_engine("sqlite:///:memory:")
    error = _assert_fails_closed(engine, "missing_table")
    assert error.problems == ("missing_table",)
    assert "no provider call was made" in str(error)


@pytest.mark.parametrize(
    ("defect", "problem"),
    [
        ({"drop": ("lease_token",)}, "missing_column:lease_token"),
        ({"retype": {"lease_token": Integer()}}, "wrong_type:lease_token:INTEGER"),
        ({"retype": {"lease_token": String(8)}}, "wrong_type:lease_token:VARCHAR(8)"),
        (
            {"retype": {"credits_spent": String(16)}},
            "wrong_type:credits_spent:VARCHAR(16)",
        ),
        ({"not_null": ("lease_token",)}, "not_nullable:lease_token"),
        ({"unique": False}, "missing_unique:resource_key"),
    ],
    ids=[
        "no-lease-token",
        "int-token",
        "short-token",
        "text-credits",
        "not-null",
        "no-unique",
    ],
)
def test_sqlite_incompatible_schema_makes_zero_provider_calls(defect, problem):
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    _legacy_table(metadata, **defect)
    metadata.create_all(engine)
    error = _assert_fails_closed(engine, problem)
    assert error.problems == (problem,)


def test_schema_check_database_error_fails_closed(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'missing-dir' / 'ledger.db'}")
    error = _assert_fails_closed(engine, "schema_check_error:OperationalError")
    assert error.problems == ("schema_check_error:OperationalError",)


def test_refusal_is_not_cached_and_a_migrated_database_recovers_without_restart():
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    ledger = AcquisitionLedger(session)
    request = AcquisitionRequest(
        url="https://example.org/x", provider="powo", consumer_module="m"
    )
    with pytest.raises(LedgerSchemaUnavailableError):
        ledger.claim(request, worker_id="w")
    MODEL.create(engine)
    assert ledger.claim(request, worker_id="w").action == "acquired_lease"


def test_postgres_migration_refuses_other_dialects():
    engine = sqlite_memory_engine()
    with engine.begin() as connection, pytest.raises(RuntimeError, match="PostgreSQL"):
        apply_ledger_migration(connection)


def test_app_startup_does_not_touch_the_ledger_schema(monkeypatch):
    from fastapi.testclient import TestClient

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError("startup must not check or create the ledger schema")

    monkeypatch.setattr(schema_module, "ledger_schema_problems", _must_not_run)
    monkeypatch.setattr(schema_module, "apply_ledger_migration", _must_not_run)
    from app.main import app

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200


def test_migration_is_additive_only():
    sql = MIGRATION_PATH.read_text(encoding="utf-8").upper()
    code = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    for forbidden in (
        "DROP ",
        "TRUNCATE",
        "DELETE ",
        "UPDATE ",
        "ALTER COLUMN",
        "RENAME",
    ):
        assert forbidden not in code, forbidden
    assert "CREATE TABLE IF NOT EXISTS ACQUISITION_LEDGER" in code
    assert "ADD COLUMN IF NOT EXISTS LEASE_TOKEN VARCHAR(64)" in code


# --- PostgreSQL 16: the production migration itself --------------------------

_CATALOG_SQL = """
SELECT 'column' AS kind, column_name AS name,
       concat_ws(':', data_type, character_maximum_length, is_nullable) AS detail
  FROM information_schema.columns
 WHERE table_schema = current_schema() AND table_name = 'acquisition_ledger'
UNION ALL
SELECT 'constraint', conname, pg_get_constraintdef(oid)
  FROM pg_constraint WHERE conrelid = 'acquisition_ledger'::regclass
UNION ALL
SELECT 'index', indexname, indexdef
  FROM pg_indexes
 WHERE schemaname = current_schema() AND tablename = 'acquisition_ledger'
ORDER BY 1, 2
"""


def _catalog(engine):
    with engine.connect() as connection:
        rows = connection.execute(text(_CATALOG_SQL)).all()
    return [
        (kind, name, detail.replace(f"{_schema_of(engine)}.", ""))
        for kind, name, detail in rows
    ]


def _schema_of(engine):
    with engine.connect() as connection:
        return connection.execute(text("SELECT current_schema()")).scalar_one()


def _migrate(engine):
    with engine.begin() as connection:
        apply_ledger_migration(connection)


def _all_rows(engine, columns):
    names = ", ".join(columns)
    with engine.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(
                text(f"SELECT {names} FROM acquisition_ledger ORDER BY id")
            )
        ]


@pytest.mark.requires_postgres
def test_clean_database_migration_builds_exactly_the_model_schema():
    with disposable_postgres_schema() as (migrated, schema):
        _migrate(migrated)
        with migrated.connect() as connection:
            assert ledger_schema_problems(connection) == ()
            assert inspect(connection).get_table_names() == ["acquisition_ledger"]
        # The table is in the connection's own schema, as the unqualified
        # model resolves it -- not forced into ``public``.
        assert _schema_of(migrated) == schema
        with disposable_postgres_schema() as (modelled, _):
            MODEL.create(modelled)
            assert _catalog(migrated) == _catalog(modelled)
        names = {name for kind, name, _ in _catalog(migrated) if kind != "column"}
        assert {
            "acquisition_ledger_pkey",
            "uq_acquisition_resource_key",
            "ix_acquisition_ledger_resource_key",
            "ix_acquisition_ledger_provider",
        } <= names


@pytest.mark.requires_postgres
def test_migration_run_twice_changes_nothing():
    with disposable_postgres_schema() as (engine, _):
        _migrate(engine)
        ledger = AcquisitionLedger(sessionmaker(bind=engine)())
        request = AcquisitionRequest(
            url="https://example.org/x", provider="powo", consumer_module="m"
        )
        lease = ledger.claim(request, worker_id="w", now=T0)
        ledger.complete(
            AcquisitionRecord.completed(
                request=request, content=b"paid", provenance={"source": "fixture"}
            ),
            lease=lease,
            payload_json="paid",
        )
        ledger.session.close()
        columns = [column.name for column in MODEL.columns]
        catalog, rows = _catalog(engine), _all_rows(engine, columns)
        _migrate(engine)
        _migrate(engine)
        assert _catalog(engine) == catalog
        assert _all_rows(engine, columns) == rows


def _seed_legacy_rows(engine, table):
    """Rows as the pre-#1697 code wrote them: complete, failed, expired lease."""

    def _request(n):
        return AcquisitionRequest(
            url=f"https://example.org/taxon/{n}",
            provider="powo",
            consumer_module="lexicon",
        )

    # Synthetic ledger bookkeeping, not scientific data: every column is
    # present in every row so the insert is one executemany.
    base = {
        **{column.name: None for column in table.columns if column.name != "id"},
        "provider": "powo",
        "provenance_json": "{}",
        "consumers_json": json.dumps(["lexicon"]),
        "credits_spent": 0,
        "failure_count": 0,
        "created_at": T0,
        "updated_at": T0,
    }
    rows = [
        {
            **base,
            "resource_key": _request(1).key,
            "canonical_url": _request(1).canonical_url,
            "status": "complete",
            "payload_json": '{"cached": true}',
            "content_hash": "a" * 64,
            "credits_spent": 1,
            "retrieved_at": T0,
        },
        {
            **base,
            "resource_key": _request(2).key,
            "canonical_url": _request(2).canonical_url,
            "status": "failed",
            "failure_count": 1,
            "next_retry_at": T0 + timedelta(minutes=5),
        },
        {
            **base,
            "resource_key": _request(3).key,
            "canonical_url": _request(3).canonical_url,
            "status": "leased",
            "lease_holder": "old-worker",
            "lease_expires_at": T0 + timedelta(minutes=2),
        },
    ]
    with engine.begin() as connection:
        connection.execute(table.insert(), rows)
    return [_request(n) for n in (1, 2, 3)]


@pytest.mark.requires_postgres
def test_upgrade_from_pre_fencing_table_adds_lease_token_and_keeps_rows_usable():
    with disposable_postgres_schema() as (engine, _):
        metadata = MetaData()
        legacy = _legacy_table(metadata, drop=("lease_token",))
        metadata.create_all(engine)
        complete, failed, leased = _seed_legacy_rows(engine, legacy)

        # Before the migration: refused, zero provider calls, rows untouched.
        _assert_fails_closed(engine, "missing_column:lease_token")
        old_columns = [column.name for column in legacy.columns]
        before = _all_rows(engine, old_columns)

        _migrate(engine)
        with engine.connect() as connection:
            assert ledger_schema_problems(connection) == ()
        assert _all_rows(engine, old_columns) == before
        assert _all_rows(engine, ["lease_token"]) == [(None,), (None,), (None,)]
        _migrate(engine)  # idempotent on the upgraded table too
        assert _all_rows(engine, old_columns) == before

        later = T0 + timedelta(minutes=10)
        ledger = AcquisitionLedger(sessionmaker(bind=engine)())
        # The completed legacy row is still a zero-fetch cache hit.
        assert ledger.claim(complete, worker_id="new", now=later).action == "cache_hit"
        assert ledger.cached_payload(complete.key) == '{"cached": true}'
        # The failed row past its retry window and the expired legacy lease are
        # taken over through the NULL-token compare-and-swap, then fenced.
        for request in (failed, leased):
            lease = ledger.claim(request, worker_id="new", now=later)
            assert lease.action == "acquired_lease" and lease.lease_token
            assert (
                ledger.claim(request, worker_id="other", now=later).action
                == "in_flight"
            )
            ledger.complete(
                AcquisitionRecord.completed(
                    request=request,
                    content=b"paid",
                    provenance={"source": "fixture"},
                    credits_spent=1,
                ),
                lease=lease,
                payload_json="paid",
            )
        ledger.session.close()
        rows = {
            key: (status, credits, failures)
            for key, status, credits, failures in _all_rows(
                engine, ["resource_key", "status", "credits_spent", "failure_count"]
            )
        }
        assert rows == {
            complete.key: ("complete", 1, 0),
            failed.key: ("complete", 1, 1),
            leased.key: ("complete", 1, 0),
        }


@pytest.mark.requires_postgres
@pytest.mark.parametrize(
    ("defect", "problem"),
    [
        ("DROP TABLE acquisition_ledger", "missing_table"),
        (
            "ALTER TABLE acquisition_ledger DROP COLUMN lease_token",
            "missing_column:lease_token",
        ),
        (
            (
                "ALTER TABLE acquisition_ledger ALTER COLUMN lease_token "
                "TYPE INTEGER USING NULL"
            ),
            "wrong_type:lease_token:INTEGER",
        ),
        (
            (
                "ALTER TABLE acquisition_ledger ALTER COLUMN lease_expires_at "
                "TYPE TIMESTAMP WITHOUT TIME ZONE"
            ),
            "wrong_type:lease_expires_at:TIMESTAMP WITHOUT TIME ZONE",
        ),
        (
            "ALTER TABLE acquisition_ledger DROP CONSTRAINT uq_acquisition_resource_key",
            "missing_unique:resource_key",
        ),
    ],
    ids=["no-table", "no-lease-token", "int-token", "naive-timestamp", "no-unique"],
)
def test_postgres_missing_or_incompatible_schema_makes_zero_provider_calls(
    defect, problem
):
    with disposable_postgres_schema() as (engine, _):
        _migrate(engine)
        with engine.begin() as connection:
            connection.execute(text(defect))
        error = _assert_fails_closed(engine, problem)
        assert error.problems == (problem,)


@pytest.mark.requires_postgres
def test_postgres_service_on_migrated_schema_pays_once_then_serves_cache():
    with disposable_postgres_schema() as (engine, _):
        _migrate(engine)
        mapper = _spy_mapper()
        make = sessionmaker(bind=engine)
        assert (
            _map(SharedFirecrawlFederationService(make(), mapper=mapper))[0]
            == "fetched"
        )
        status, profile = _map(
            SharedFirecrawlFederationService(make(), mapper=mapper), module="matrix"
        )
        assert (status, profile is not None) == ("cache_hit", True)
        assert mapper.map_source.call_count == 1


# --- The owner-run activation script -----------------------------------------


def _activation_script():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "activate_acquisition_ledger_schema.py"
    )
    spec = importlib.util.spec_from_file_location(
        "activate_acquisition_ledger_schema", path
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _point_at(monkeypatch, schema, tmp_path):
    dsn = postgres_base_dsn()
    separator = "&" if "?" in dsn else "?"
    monkeypatch.delenv("PGHOST", raising=False)
    monkeypatch.setenv(
        "DATABASE_URL",
        f"{dsn}{separator}options=-csearch_path%3D{schema}&client_encoding=utf8",
    )
    evidence = tmp_path / "evidence.json"
    monkeypatch.setenv(
        "CALYX_ACQUISITION_LEDGER_MIGRATION_EVIDENCE_PATH", str(evidence)
    )
    return evidence


@pytest.mark.requires_postgres
def test_activation_script_preflights_read_only_and_applies_only_when_confirmed(
    monkeypatch, tmp_path, capsys
):
    script = _activation_script()
    with disposable_postgres_schema() as (engine, schema):
        evidence = _point_at(monkeypatch, schema, tmp_path)
        monkeypatch.delenv(script.CONFIRM_ENV, raising=False)

        assert script.run(apply_requested=False) == 0
        report = json.loads(evidence.read_text())
        assert report["problems_before"] == ["missing_table"]
        assert report["schema_ready"] is False and report["applied"] is False
        assert inspect(engine).get_table_names() == []

        assert script.run(apply_requested=True) == 2
        report = json.loads(evidence.read_text())
        assert "EXPLICIT_APPLY_CONFIRMATION_REQUIRED" in report["blockers"]
        assert report["database_mutation_attempted"] is False
        assert inspect(engine).get_table_names() == []

        monkeypatch.setenv(script.CONFIRM_ENV, script.CONFIRMATION)
        assert script.run(apply_requested=True) == 0
        report = json.loads(evidence.read_text())
        assert report["applied"] is True and report["problems_after"] == []
        assert report["provider_calls"] == 0
        assert postgres_base_dsn() not in capsys.readouterr().out
        with engine.connect() as connection:
            assert ledger_schema_problems(connection) == ()


def test_activation_script_refuses_a_non_postgres_database(monkeypatch, tmp_path):
    script = _activation_script()
    for name in ("PGHOST", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    evidence = tmp_path / "evidence.json"
    monkeypatch.setenv(
        "CALYX_ACQUISITION_LEDGER_MIGRATION_EVIDENCE_PATH", str(evidence)
    )
    assert script.run(apply_requested=True) == 2
    report = json.loads(evidence.read_text())
    assert report["blockers"] == ["POSTGRESQL_DATABASE_REQUIRED"]
    assert report["database_mutation_attempted"] is False
