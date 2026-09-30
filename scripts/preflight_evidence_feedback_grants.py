#!/usr/bin/env python3
"""Evidence-feedback schema and grants preflight (read-only).

Connects with ``DATABASE_URL`` (or ``--database-url-env NAME``) and reports, for
``current_user``, whether the ``oc_evidence_feedback`` schema, tables, indexes
and sequence exist and whether the role holds the privileges the runtime store
needs: USAGE on the schema, SELECT/INSERT/UPDATE on each table and USAGE on
the ``case_events`` sequence.

Read-only by construction: the session and transaction are ``READ ONLY`` and
the script only reads ``pg_catalog`` and calls the ``has_*_privilege``
functions. It performs no DDL and no DML, and it never prints the connection
string.

Output is one JSON document. Exit codes: 0 everything present and granted,
1 something missing, 2 the database could not be checked.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evidence_feedback.postgres_repository import (
    ADDITIVE_INDEXES,
    SCHEMA,
    TABLES,
)

TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE")
# (table, serial column) pairs whose sequences the runtime uses on INSERT.
SERIAL_COLUMNS = (("case_events", "event_id"),)
INDEXES = (
    "case_events_case_idx",
    "cases_status_idx",
    *(n for n, _ in ADDITIVE_INDEXES),
)


# Presence comes from pg_catalog, which every role can read. ``to_regclass``
# cannot be used for a role without USAGE on the schema: PostgreSQL raises
# InsufficientPrivilege instead of answering, which is exactly the role this
# preflight exists to diagnose.
RELATION_OID_SQL = (
    "SELECT c.oid FROM pg_catalog.pg_class c "
    "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = %s AND c.relname = %s"
)
# The sequence owned by a serial column (what pg_get_serial_sequence resolves,
# without its name lookup).
SERIAL_SEQUENCE_SQL = (
    "SELECT s.oid, quote_ident(sn.nspname) || '.' || quote_ident(s.relname) "
    "FROM pg_catalog.pg_depend d "
    "JOIN pg_catalog.pg_class s ON s.oid = d.objid AND s.relkind = 'S' "
    "JOIN pg_catalog.pg_namespace sn ON sn.oid = s.relnamespace "
    "JOIN pg_catalog.pg_attribute a "
    "ON a.attrelid = d.refobjid AND a.attnum = d.refobjsubid "
    "WHERE d.classid = 'pg_catalog.pg_class'::regclass "
    "AND d.refclassid = 'pg_catalog.pg_class'::regclass "
    "AND d.refobjid = %s AND a.attname = %s AND d.deptype IN ('a', 'i')"
)


def _one(cur, sql: str, params: tuple = ()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return row[0] if row else None


def _relation_oid(cur, name: str):
    return _one(cur, RELATION_OID_SQL, (SCHEMA, name))


def inspect(conn) -> dict[str, object]:
    """Read-only inspection of the evidence-feedback objects for current_user."""

    missing: list[str] = []
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
        role = _one(cur, "SELECT current_user")
        schema_present = bool(
            _one(
                cur,
                "SELECT 1 FROM pg_catalog.pg_namespace WHERE nspname = %s",
                (SCHEMA,),
            )
        )
        schema_usage = bool(
            schema_present
            and _one(
                cur, "SELECT has_schema_privilege(current_user, %s, 'USAGE')", (SCHEMA,)
            )
        )
        if not schema_present:
            missing.append(f"SCHEMA {SCHEMA}")
        elif not schema_usage:
            missing.append(f"USAGE ON SCHEMA {SCHEMA}")

        tables = []
        table_oids = {}
        for table in TABLES:
            qualified = f"{SCHEMA}.{table}"
            oid = _relation_oid(cur, table)
            table_oids[table] = oid
            privileges = {}
            for privilege in TABLE_PRIVILEGES:
                granted = bool(
                    oid is not None
                    and _one(
                        cur,
                        "SELECT has_table_privilege(current_user, %s::oid, %s)",
                        (oid, privilege),
                    )
                )
                privileges[privilege] = granted
                if oid is not None and not granted:
                    missing.append(f"{privilege} ON TABLE {qualified}")
            if oid is None:
                missing.append(f"TABLE {qualified}")
            tables.append(
                {
                    "name": qualified,
                    "present": oid is not None,
                    "privileges": privileges,
                }
            )

        sequences = []
        for table, column in SERIAL_COLUMNS:
            qualified = f"{SCHEMA}.{table}"
            sequence_oid, sequence = None, None
            if table_oids.get(table) is not None:
                cur.execute(SERIAL_SEQUENCE_SQL, (table_oids[table], column))
                row = cur.fetchone()
                if row:
                    sequence_oid, sequence = row
            usage = bool(
                sequence_oid is not None
                and _one(
                    cur,
                    "SELECT has_sequence_privilege(current_user, %s::oid, 'USAGE')",
                    (sequence_oid,),
                )
            )
            if sequence is None:
                missing.append(f"SEQUENCE for {qualified}.{column}")
            elif not usage:
                missing.append(f"USAGE ON SEQUENCE {sequence}")
            sequences.append(
                {
                    "name": sequence or f"{qualified}.{column} sequence",
                    "present": sequence is not None,
                    "usage": usage,
                }
            )

        indexes = []
        for name in INDEXES:
            present = _relation_oid(cur, name) is not None
            if not present:
                missing.append(f"INDEX {SCHEMA}.{name}")
            indexes.append({"name": f"{SCHEMA}.{name}", "present": present})

        # Informational only: whether this role could bootstrap absent objects itself.
        can_create_schema = bool(
            _one(
                cur,
                "SELECT has_database_privilege(current_user, current_database(), 'CREATE')",
            )
        )
    conn.rollback()
    return {
        "status": "OK" if not missing else "MISSING",
        "role": role,
        "schema": {"name": SCHEMA, "present": schema_present, "usage": schema_usage},
        "tables": tables,
        "sequences": sequences,
        "indexes": indexes,
        "missing": missing,
        "role_can_create_schema": can_create_schema,
        "ddl_performed": False,
        "migration": "migrations/EVIDENCE-FEEDBACK-001.sql",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--database-url-env",
        default="DATABASE_URL",
        help="name of the environment variable holding the connection string",
    )
    args = parser.parse_args(argv)
    dsn = os.environ.get(args.database_url_env, "").strip()
    if not dsn:
        print(
            json.dumps(
                {
                    "status": "UNAVAILABLE",
                    "reason": f"{args.database_url_env} is not set",
                }
            )
        )
        return 2
    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=10, autocommit=False) as conn:
            conn.read_only = True
            report = inspect(conn)
    except Exception as exc:  # noqa: BLE001 - reported, never the DSN
        print(json.dumps({"status": "UNAVAILABLE", "reason": type(exc).__name__}))
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
