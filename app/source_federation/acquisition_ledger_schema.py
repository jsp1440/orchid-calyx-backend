"""Schema migration and fail-closed schema check for the acquisition ledger.

Production schema for this ledger is owned by the idempotent SQL file
``migrations/20260930_acquisition_ledger.sql``, applied explicitly (see
``scripts/activate_acquisition_ledger_schema.py``). The application never
creates or alters the table at request time.

:func:`ledger_schema_problems` is the read-only check the ledger runs before it
hands out a lease, and therefore before any paid provider call. A missing
table, a missing column, an incompatible type or nullability, or a missing
unique key on ``resource_key`` (claim coalescing depends on it) is reported as
:class:`LedgerSchemaUnavailableError`; the caller makes no provider call.
Nothing here runs at import or application startup.
"""

from __future__ import annotations

import time
import weakref
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, Integer, String, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .acquisition_models import AcquisitionLedgerRow

MIGRATION_ID = "20260930_acquisition_ledger"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / f"{MIGRATION_ID}.sql"
)
TABLE = AcquisitionLedgerRow.__table__
UNIQUE_KEY_COLUMNS = ("resource_key",)
MISSING_UNIQUE = "missing_unique:resource_key"


class LedgerSchemaUnavailableError(RuntimeError):
    """The ledger table is absent or incompatible; no lease was handed out.

    ``problems`` names each defect (``missing_table``,
    ``missing_column:<name>``, ``wrong_type:<name>:<found>``,
    ``not_nullable:<name>``, ``missing_unique:resource_key`` (no valid,
    non-partial unique key on it) or ``schema_check_error:<exception type>``).
    No provider call was made.
    """

    code = "ledger_schema_unavailable"

    def __init__(self, problems: tuple[str, ...]) -> None:
        self.problems = tuple(problems)
        super().__init__(
            "acquisition ledger schema unavailable ("
            + ", ".join(self.problems)
            + "); no lease was granted and no provider call was made. Apply "
            f"migrations/{MIGRATION_ID}.sql"
        )


def migration_sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def apply_ledger_migration(connection: Connection) -> None:
    """Run the migration on ``connection`` inside the caller's transaction.

    PostgreSQL only: the file uses ``ADD COLUMN IF NOT EXISTS`` and a DO block.
    SQLite development databases build the table from the model instead.
    """
    if connection.dialect.name != "postgresql":
        raise RuntimeError(
            f"{MIGRATION_ID} is PostgreSQL DDL; got dialect {connection.dialect.name!r}"
        )
    if not connection.in_transaction():
        raise RuntimeError(
            f"{MIGRATION_ID} must run inside one transaction (engine.begin())"
        )
    connection.exec_driver_sql(migration_sql())


def _type_problem(name: str, expected, found, dialect: str) -> str | None:
    label = f"wrong_type:{name}:{found}"
    try:
        found_python = found.python_type
    except NotImplementedError:
        return label
    if isinstance(expected, DateTime):
        if found_python is not datetime:
            return label
        # A PostgreSQL ``timestamp without time zone`` would silently shift
        # the UTC instants the ledger writes by the session time zone.
        if dialect == "postgresql" and expected.timezone and not found.timezone:
            return f"wrong_type:{name}:TIMESTAMP WITHOUT TIME ZONE"
        return None
    if isinstance(expected, Integer):
        return None if found_python is int else label
    if isinstance(expected, String):
        if found_python is not str:
            return label
        found_length = getattr(found, "length", None)
        if expected.length and found_length and found_length < expected.length:
            return label
        return None
    return None


def ledger_schema_problems(connection: Connection) -> tuple[str, ...]:
    """Every way the live table differs from what the ledger needs; () if none."""
    inspector = inspect(connection)
    schema = TABLE.schema
    if not inspector.has_table(TABLE.name, schema=schema):
        return ("missing_table",)
    dialect = connection.dialect.name
    found = {
        col["name"]: col for col in inspector.get_columns(TABLE.name, schema=schema)
    }
    problems: list[str] = []
    for column in TABLE.columns:
        live = found.get(column.name)
        if live is None:
            problems.append(f"missing_column:{column.name}")
            continue
        problem = _type_problem(column.name, column.type, live["type"], dialect)
        if problem:
            problems.append(problem)
        if column.nullable and not live.get("nullable", True):
            problems.append(f"not_nullable:{column.name}")
    if not unique_key_present(connection):
        problems.append(MISSING_UNIQUE)
    return tuple(problems)


# The one unique key claim coalescing may rely on: NON-partial, on exactly
# ``resource_key`` (no expression), enforced immediately, and valid and ready.
# A partial index (``WHERE status = 'complete'``) or an INVALID one left by a
# failed ``CREATE UNIQUE INDEX CONCURRENTLY`` does not stop a second insert of
# the same key, i.e. a second paid lease. A unique or primary-key constraint is
# backed by exactly such an index, so it is covered here too.
_PG_UNIQUE_KEY_SQL = text(
    """
    SELECT 1
      FROM pg_index AS i
      JOIN pg_attribute AS a
        ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
     WHERE i.indrelid = to_regclass(:relation)
       AND i.indisunique
       AND i.indisvalid
       AND i.indisready
       AND i.indislive
       AND i.indimmediate
       AND i.indpred IS NULL
       AND i.indexprs IS NULL
       AND i.indnkeyatts = 1
       AND a.attname = :column
     LIMIT 1
    """
)


def _relation_name() -> str:
    return f"{TABLE.schema}.{TABLE.name}" if TABLE.schema else TABLE.name


def unique_key_present(connection: Connection) -> bool:
    """Whether a real (non-partial, valid, ready) unique key on resource_key exists.

    Cheap: one catalog query on PostgreSQL. Other dialects are read through
    the SQLAlchemy inspector, ignoring partial (``sqlite_where``) and
    expression indexes.
    """
    (column,) = UNIQUE_KEY_COLUMNS
    if connection.dialect.name == "postgresql":
        row = connection.execute(
            _PG_UNIQUE_KEY_SQL, {"relation": _relation_name(), "column": column}
        ).first()
        return row is not None
    inspector = inspect(connection)
    schema = TABLE.schema
    for item in inspector.get_unique_constraints(TABLE.name, schema=schema):
        if tuple(item["column_names"]) == UNIQUE_KEY_COLUMNS:
            return True
    for item in inspector.get_indexes(TABLE.name, schema=schema):
        options = item.get("dialect_options") or {}
        partial = any(
            key.endswith("_where") and value is not None
            for key, value in options.items()
        )
        if (
            item.get("unique")
            and not partial
            and not item.get("expressions")
            and tuple(item["column_names"]) == UNIQUE_KEY_COLUMNS
        ):
            return True
    return False


#: How long a PASS is trusted before the full check runs again. The claim
#: path does not depend on it for uniqueness (it re-checks the unique key in
#: the inserting transaction, see ``AcquisitionLedger``) and turns schema SQL
#: errors into :class:`LedgerSchemaUnavailableError`; the TTL bounds how long
#: any other drift (a retyped column) can go unnoticed.
SCHEMA_PASS_TTL_SECONDS = 30.0

# engine -> monotonic deadline of its last PASS. Only a PASS is remembered, so
# a database migrated after a refusal is picked up without a restart. Weak, so
# a disposed engine never lends its verdict to a new one at the same address.
_VERIFIED_ENGINES: weakref.WeakKeyDictionary[Engine, float] = (
    weakref.WeakKeyDictionary()
)


def _engine_of(session: Session) -> Engine | None:
    bind = session.get_bind()
    if isinstance(bind, Engine):
        return bind
    return getattr(bind, "engine", None)


def forget_verified_schema(session: Session) -> None:
    """Drop the cached PASS for ``session``'s engine (the next call re-checks)."""
    engine = _engine_of(session)
    if engine is not None:
        _VERIFIED_ENGINES.pop(engine, None)


def require_ledger_schema(session: Session, *, use_cache: bool = True) -> None:
    """Raise :class:`LedgerSchemaUnavailableError` unless the schema is usable.

    Read-only. On refusal the session's transaction is rolled back, so the
    caller is left with a clean session and no lease.
    """
    engine = _engine_of(session)
    if use_cache and engine is not None:
        deadline = _VERIFIED_ENGINES.get(engine)
        if deadline is not None and time.monotonic() < deadline:
            return
    try:
        problems = ledger_schema_problems(session.connection())
    except SQLAlchemyError as exc:
        session.rollback()
        forget_verified_schema(session)
        raise LedgerSchemaUnavailableError(
            (f"schema_check_error:{type(exc).__name__}",)
        ) from exc
    if problems:
        session.rollback()
        forget_verified_schema(session)
        raise LedgerSchemaUnavailableError(problems)
    if engine is not None:
        _VERIFIED_ENGINES[engine] = time.monotonic() + SCHEMA_PASS_TTL_SECONDS
