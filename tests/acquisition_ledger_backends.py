"""Ledger engines for the acquisition-ledger suites.

``sqlite``: an in-memory database with the table built from the model, as
before. ``postgres_migrated``: a fresh schema on the disposable PostgreSQL test
database (``TEST_DATABASE_URL``, then ``DATABASE_URL``; see ``requires_postgres``
in ``tests/conftest.py``) built ONLY by the production migration
``migrations/20260930_acquisition_ledger.sql`` -- never by ``create_all`` -- and
reached through ``search_path``, exactly as the unqualified model resolves.
"""

from __future__ import annotations

import contextlib
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm.session import _sessions

from app.database import Base
from app.source_federation.acquisition_ledger_schema import apply_ledger_migration
from app.source_federation.acquisition_models import AcquisitionLedgerRow

LEDGER_BACKENDS = pytest.mark.parametrize(
    "ledger_engine",
    [
        "sqlite",
        pytest.param("postgres_migrated", marks=pytest.mark.requires_postgres),
    ],
    indirect=True,
)


def postgres_base_dsn() -> str:
    dsn = os.environ.get("TEST_DATABASE_URL") or os.environ["DATABASE_URL"]
    for prefix in ("postgresql+psycopg://", "postgres://"):
        if dsn.startswith(prefix):
            dsn = "postgresql://" + dsn[len(prefix) :]
    return dsn


def _close_sessions_bound_to(engine) -> None:
    """Close (rolling back) the sessions a test left open on ``engine`` only.

    Tests create sessions freely and never close them; on PostgreSQL an idle
    transaction would block the schema drop. ``_sessions`` is SQLAlchemy's
    weak registry of live sessions; other tests' sessions are left alone.
    """
    for session in list(_sessions.values()):
        if session.bind is engine:
            session.close()


@contextlib.contextmanager
def disposable_postgres_schema(**engine_kwargs):
    """Yield ``(engine, schema)`` for an empty schema first on ``search_path``.

    The schema is dropped afterwards; backends the test left open are
    terminated first so an idle-in-transaction session cannot block the drop.
    """
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict

    base_dsn = postgres_base_dsn()
    schema = "acq_ledger_" + uuid4().hex[:16]
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    params = conninfo_to_dict(base_dsn)
    params["options"] = f"-c search_path={schema}"
    params["application_name"] = schema
    # A cluster initialised as SQL_ASCII would make psycopg return bytes,
    # which SQLAlchemy's version probe cannot parse.
    params["client_encoding"] = "utf8"
    engine = create_engine(
        "postgresql+psycopg://", connect_args=params, **engine_kwargs
    )
    try:
        yield engine, schema
    finally:
        _close_sessions_bound_to(engine)
        engine.dispose()
        with psycopg.connect(base_dsn, autocommit=True) as conn:
            conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE application_name = %s AND pid <> pg_backend_pid()",
                (schema,),
            )
            conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


@contextlib.contextmanager
def migrated_postgres_engine(**engine_kwargs):
    with disposable_postgres_schema(**engine_kwargs) as (engine, _schema):
        with engine.begin() as connection:
            apply_ledger_migration(connection)
        yield engine


def sqlite_memory_engine():
    engine = create_engine("sqlite:///:memory:")
    # Only the ledger table: the shared Base also carries schema-qualified
    # tables (e.g. research_station.*) that SQLite cannot create.
    Base.metadata.create_all(engine, tables=[AcquisitionLedgerRow.__table__])
    return engine


@pytest.fixture(name="ledger_engine")
def ledger_engine_fixture(request):
    """Import this into a suite; tests request it as ``ledger_engine``."""
    backend = getattr(request, "param", "sqlite")
    if backend == "sqlite":
        engine = sqlite_memory_engine()
        try:
            yield engine
        finally:
            engine.dispose()
        return
    if backend != "postgres_migrated":
        raise ValueError(f"unknown ledger backend {backend!r}")
    with migrated_postgres_engine() as engine:
        yield engine
