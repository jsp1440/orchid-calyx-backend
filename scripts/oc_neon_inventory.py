#!/usr/bin/env python3
"""Read-only inventory of the Neon/Orchid Continuum PostgreSQL knowledge store.

Uses DATABASE_URL intentionally, not app.database.get_database_url(), because
the target of this audit is the historical Continuum/Neon scientific store.
No DDL/DML, sampling of scientific rows, or credential output is performed.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row

SYSTEM_SCHEMAS = {"pg_catalog", "information_schema"}


def inventory(dsn: str) -> dict:
    with psycopg.connect(
        dsn,
        row_factory=dict_row,
        options="-c default_transaction_read_only=on",
    ) as conn, conn.cursor() as cur:
        cur.execute("SHOW transaction_read_only")
        state = cur.fetchone()["transaction_read_only"]
        if state != "on":
            raise RuntimeError("READ_ONLY_PREFLIGHT_FAILED")

        cur.execute(
            """
            SELECT n.nspname AS schema_name,
                   c.relname AS relation_name,
                   CASE c.relkind
                     WHEN 'r' THEN 'table'
                     WHEN 'p' THEN 'partitioned_table'
                     WHEN 'v' THEN 'view'
                     WHEN 'm' THEN 'materialized_view'
                     ELSE c.relkind::text
                   END AS relation_type,
                   COALESCE(s.n_live_tup, 0)::bigint AS estimated_live_rows,
                   CASE WHEN c.relkind IN ('r','p','m')
                     THEN pg_total_relation_size(c.oid)
                     ELSE 0
                   END::bigint AS total_bytes
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
            WHERE c.relkind IN ('r','p','v','m')
              AND n.nspname NOT IN ('pg_catalog','information_schema')
              AND n.nspname NOT LIKE 'pg_toast%'
              AND n.nspname NOT LIKE 'pg_temp%'
            ORDER BY n.nspname, c.relname
            """
        )
        relations = [dict(row) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT table_schema AS schema_name,
                   count(*)::int AS column_count
            FROM information_schema.columns
            WHERE table_schema NOT IN ('pg_catalog','information_schema')
            GROUP BY table_schema
            ORDER BY table_schema
            """
        )
        column_counts = {row["schema_name"]: row["column_count"] for row in cur.fetchall()}

        cur.execute("SELECT current_database() AS database_name, version() AS server_version")
        identity = dict(cur.fetchone())

    schemas: dict[str, dict] = {}
    for rel in relations:
        schema = schemas.setdefault(
            rel["schema_name"],
            {
                "relations": 0,
                "estimated_live_rows": 0,
                "total_bytes": 0,
                "column_count": column_counts.get(rel["schema_name"], 0),
                "relation_names": [],
            },
        )
        schema["relations"] += 1
        schema["estimated_live_rows"] += int(rel["estimated_live_rows"] or 0)
        schema["total_bytes"] += int(rel["total_bytes"] or 0)
        schema["relation_names"].append(
            {"name": rel["relation_name"], "type": rel["relation_type"]}
        )

    return {
        "schema": "oc.neon_inventory.v1",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "read_only_verified": True,
        "database_name": identity["database_name"],
        "server_version": identity["server_version"],
        "schema_count": len(schemas),
        "relation_count": len(relations),
        "schemas": schemas,
        "relations": relations,
        "notes": [
            "Row counts are PostgreSQL statistics estimates, not full-table scans.",
            "No scientific row contents were sampled.",
            "No raw DSN, host credential, password, or API key is emitted.",
        ],
    }


def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required for the Neon inventory")
    print(json.dumps(inventory(dsn), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
