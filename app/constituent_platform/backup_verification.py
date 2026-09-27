"""Backup/restore verification harness for the society CRM (OC-CRM-BACKUP-RESTORE-001).

The harness proves, against a real PostgreSQL, that a ``pg_dump``/``pg_restore``
round trip preserves *all* CRM state -- every row of every table in the configured
schemas, plus the structure that tenant safety depends on:

* row count and a content digest per table (tables are discovered from the catalog,
  so tables added later -- payments, donations, ... -- are covered with no code
  change as long as their schema is in the configured list);
* RLS enabled/forced flags and policy definitions (tenant isolation);
* non-internal triggers and whether they are enabled (audit append-only guards);
* constraints and their ``convalidated`` flag (composite tenant foreign keys);
* indexes, column definitions, table ACLs, and schema functions;
* sequence positions (a restored sequence that lags would reissue ids).

Reading privileges
------------------
Fingerprints must be taken as the table owner or a superuser, **never** under the
RLS runtime role ``oc_crm_runtime``: RLS would silently hide other tenants' rows and
the fingerprint would look complete while describing one tenant. The fingerprint
session therefore sets ``row_security = off``; with that setting PostgreSQL raises an
error instead of filtering if RLS would apply to the reading role (for example a
non-owner, or a ``FORCE ROW LEVEL SECURITY`` table read by its owner). A fingerprint
either sees every row or fails loudly.

Roles
-----
Roles (including the NOLOGIN ``oc_crm_runtime`` role and its memberships) are
cluster-level objects and are NOT contained in ``pg_dump`` output. A restore into a
cluster that lacks them fails (policies and GRANTs reference them). The drill
therefore checks after restore that every role referenced by a CRM policy exists in
the target cluster and then exercises ``SET LOCAL ROLE oc_crm_runtime`` with a tenant
context in the restored database to prove isolation still works there.

Nothing here touches the source database except read-only queries inside one
``REPEATABLE READ READ ONLY`` transaction whose snapshot is shared with ``pg_dump``
(``--snapshot``), so the fingerprint and the dump describe exactly the same state
even on a live database. All mutation (restore, functional probes) happens only in
a freshly created, uniquely named scratch database.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.constituent_platform.tenant_db import RUNTIME_ROLE, tenant_transaction

DEFAULT_SCHEMAS: tuple[str, ...] = ("oc_constituent", "oc_communications")
DEFAULT_APPEND_ONLY_TABLES: tuple[str, ...] = (
    "oc_constituent.crm_audit_events",
    "oc_constituent.membership_renewals",
)
SCRATCH_PREFIX = "oc_restore_drill_"
FINGERPRINT_VERSION = 1
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_TENANT_QUAL = re.compile(
    r"^\(*\s*\"?([a-z_][a-z0-9_]*)\"?\s*=\s*oc_constituent\.current_tenant_id\(\)\s*\)*$"
)
_ROW_LOCALIZE_LIMIT = 1_000_000
_ROW_EXAMPLES = 20

# Session settings that make text/JSON rendering of values independent of the
# connecting client and server defaults, so the same rows hash identically before
# and after a restore (and across clusters with different defaults).
_CANONICAL_SETTINGS: tuple[tuple[str, str], ...] = (
    ("TimeZone", "UTC"),
    ("DateStyle", "ISO, YMD"),
    ("IntervalStyle", "postgres"),
    ("extra_float_digits", "1"),
    ("bytea_output", "hex"),
    ("row_security", "off"),
)


# ---------------------------------------------------------------------------
# DSN handling (never print passwords)
# ---------------------------------------------------------------------------
def _normalize_dsn(dsn: str) -> str:
    return re.sub(r"^postgres(ql)?\+\w+://", "postgresql://", dsn.strip())


def redact_dsn(dsn: str | None) -> str:
    """Render a DSN for humans with any password removed."""
    if not dsn:
        return "<unset>"
    try:
        params = conninfo_to_dict(_normalize_dsn(dsn))
    except Exception:  # noqa: BLE001 - unparsable DSN: fall back to regex redaction
        return redact_text(dsn)
    if "password" in params:
        params["password"] = "***"
    return " ".join(f"{key}={value}" for key, value in sorted(params.items()))


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    out = re.sub(r"://([^:/@\s]+):[^@\s]*@", r"://\1:***@", text)
    out = re.sub(r"(password\s*=\s*)('[^']*'|\S+)", r"\1***", out, flags=re.IGNORECASE)
    for secret in secrets:
        if secret:
            out = out.replace(secret, "***")
    return out


def _client_conninfo(dsn: str, *, dbname: str | None = None) -> tuple[str, dict[str, str]]:
    """Split a DSN into a password-free conninfo plus an environment for libpq tools."""
    params = conninfo_to_dict(_normalize_dsn(dsn))
    password = params.pop("password", None)
    if dbname is not None:
        params["dbname"] = dbname
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = str(password)
    return make_conninfo(**params), env


def _dsn_with_dbname(dsn: str, dbname: str) -> str:
    params = conninfo_to_dict(_normalize_dsn(dsn))
    params["dbname"] = dbname
    return make_conninfo(**params)


def _dsn_password(dsn: str) -> str | None:
    try:
        value = conninfo_to_dict(_normalize_dsn(dsn)).get("password")
    except Exception:  # noqa: BLE001
        return None
    return str(value) if value else None


def validate_schemas(schemas: Iterable[str]) -> list[str]:
    result: list[str] = []
    for schema in schemas:
        name = schema.strip()
        if not name:
            continue
        if not _IDENTIFIER.match(name):
            raise ValueError(f"invalid schema name {name!r}: expected a lower-case SQL identifier")
        if name not in result:
            result.append(name)
    if not result:
        raise ValueError("at least one schema is required")
    return result


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------
@contextmanager
def _read_scope(conn: psycopg.Connection):
    """Run inside the caller's open transaction, or a private one if none is open."""
    idle = conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
    if idle and conn.autocommit:
        with conn.transaction():
            yield
    elif idle:
        try:
            yield
        finally:
            conn.rollback()
    else:
        yield


def _apply_canonical_settings(conn: psycopg.Connection) -> None:
    for name, value in _CANONICAL_SETTINGS:
        conn.execute("SELECT set_config(%s, %s, true)", (name, value))


def _qualified(schema: str, table: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))


def _discover_tables(conn: psycopg.Connection, schemas: Sequence[str]) -> list[dict[str, Any]]:
    return [
        {
            "oid": row[0],
            "schema": row[1],
            "table": row[2],
            "relkind": row[3],
            "rls_enabled": bool(row[4]),
            "rls_forced": bool(row[5]),
            "acl": sorted(row[6] or []),
        }
        for row in conn.execute(
            """
            SELECT c.oid, n.nspname, c.relname, c.relkind::text, c.relrowsecurity,
                   c.relforcerowsecurity, c.relacl::text[]
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'p')
            ORDER BY n.nspname, c.relname
            """,
            (list(schemas),),
        ).fetchall()
    ]


def _table_columns(conn: psycopg.Connection, oid: int) -> list[dict[str, Any]]:
    return [
        {
            "name": row[0],
            "type": row[1],
            "not_null": bool(row[2]),
            "default": row[3],
            "collatable": bool(row[4]),
        }
        for row in conn.execute(
            """
            SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
                   pg_get_expr(d.adbin, d.adrelid), a.attcollation <> 0
            FROM pg_attribute a
            LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE a.attrelid = %s AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
            """,
            (oid,),
        ).fetchall()
    ]


def _primary_key(conn: psycopg.Connection, oid: int) -> list[str]:
    row = conn.execute(
        """
        SELECT array_agg(a.attname ORDER BY k.ord)
        FROM pg_index i
        CROSS JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
        WHERE i.indrelid = %s AND i.indisprimary
        """,
        (oid,),
    ).fetchone()
    return list(row[0]) if row and row[0] else []


def _order_by(columns: list[dict[str, Any]], pk: list[str]) -> sql.Composable:
    collatable = {col["name"] for col in columns if col["collatable"]}
    if pk:
        parts = [
            sql.SQL("t.{} COLLATE \"C\"").format(sql.Identifier(name))
            if name in collatable
            else sql.SQL("t.{}").format(sql.Identifier(name))
            for name in pk
        ]
        return sql.SQL(", ").join(parts)
    # No primary key: order by the canonical row text itself (deterministic).
    return sql.SQL("row_to_json(t)::text COLLATE \"C\"")


def _content_digest(
    conn: psycopg.Connection, schema: str, table: str, order_by: sql.Composable
) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    query = sql.SQL("SELECT row_to_json(t)::text FROM {} AS t ORDER BY {}").format(
        _qualified(schema, table), order_by
    )
    name = f"oc_fp_{uuid.uuid4().hex[:12]}"
    with conn.cursor(name=name) as cur:
        cur.itersize = 2000
        cur.execute(query)
        for (text,) in cur:
            digest.update(text.encode("utf-8"))
            digest.update(b"\n")
            count += 1
    return count, digest.hexdigest()


def _policies(conn: psycopg.Connection, oid: int) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
        """
        SELECT p.polname, p.polpermissive, p.polcmd::text,
               ARRAY(
                   SELECT CASE WHEN r = 0 THEN 'public' ELSE pg_get_userbyid(r)::text END
                   FROM unnest(p.polroles) AS r ORDER BY 1
               ),
               pg_get_expr(p.polqual, p.polrelid), pg_get_expr(p.polwithcheck, p.polrelid)
        FROM pg_policy p WHERE p.polrelid = %s ORDER BY p.polname
        """,
        (oid,),
    ).fetchall():
        result[row[0]] = {
            "permissive": bool(row[1]),
            "command": row[2],
            "roles": list(row[3]),
            "using": row[4],
            "with_check": row[5],
        }
    return result


def _triggers(conn: psycopg.Connection, oid: int) -> dict[str, dict[str, Any]]:
    return {
        row[0]: {"enabled": row[1], "definition": row[2]}
        for row in conn.execute(
            """
            SELECT t.tgname, t.tgenabled::text, pg_get_triggerdef(t.oid)
            FROM pg_trigger t WHERE t.tgrelid = %s AND NOT t.tgisinternal
            ORDER BY t.tgname
            """,
            (oid,),
        ).fetchall()
    }


def _constraints(conn: psycopg.Connection, oid: int) -> dict[str, dict[str, Any]]:
    return {
        row[0]: {"type": row[1], "validated": bool(row[2]), "definition": row[3]}
        for row in conn.execute(
            """
            SELECT conname, contype::text, convalidated, pg_get_constraintdef(oid)
            FROM pg_constraint WHERE conrelid = %s ORDER BY conname
            """,
            (oid,),
        ).fetchall()
    }


def _indexes(conn: psycopg.Connection, oid: int) -> dict[str, str]:
    return {
        row[0]: row[1]
        for row in conn.execute(
            """
            SELECT c.relname, pg_get_indexdef(i.indexrelid)
            FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid
            WHERE i.indrelid = %s ORDER BY c.relname
            """,
            (oid,),
        ).fetchall()
    }


def _functions(conn: psycopg.Connection, schemas: Sequence[str]) -> dict[str, dict[str, Any]]:
    return {
        f"{row[0]}.{row[1]}({row[2]})": {
            "security_definer": bool(row[3]),
            "source_sha256": hashlib.sha256((row[4] or "").encode("utf-8")).hexdigest(),
        }
        for row in conn.execute(
            """
            SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid),
                   p.prosecdef, p.prosrc
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = ANY(%s)
            ORDER BY 1, 2, 3
            """,
            (list(schemas),),
        ).fetchall()
    }


def _sequences(conn: psycopg.Connection, schemas: Sequence[str]) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT sn.nspname, s.relname, tn.nspname, t.relname, a.attname,
               format_type(a.atttypid, a.atttypmod)
        FROM pg_class s
        JOIN pg_namespace sn ON sn.oid = s.relnamespace
        LEFT JOIN pg_depend d
            ON d.classid = 'pg_class'::regclass AND d.objid = s.oid
           AND d.refclassid = 'pg_class'::regclass AND d.deptype IN ('a', 'i')
        LEFT JOIN pg_class t ON t.oid = d.refobjid
        LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
        LEFT JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
        WHERE s.relkind = 'S' AND sn.nspname = ANY(%s)
        ORDER BY sn.nspname, s.relname
        """,
        (list(schemas),),
    ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for seq_schema, seq_name, tbl_schema, tbl_name, column, column_type in rows:
        last_value, is_called = conn.execute(
            sql.SQL("SELECT last_value, is_called FROM {}").format(_qualified(seq_schema, seq_name))
        ).fetchone()
        next_value = int(last_value) + 1 if is_called else int(last_value)
        entry: dict[str, Any] = {
            "last_value": int(last_value),
            "is_called": bool(is_called),
            "next_value": next_value,
            "owned_by": f"{tbl_schema}.{tbl_name}.{column}" if column else None,
            "max_owned_value": None,
        }
        if column and column_type in {"bigint", "integer", "smallint"}:
            max_value = conn.execute(
                sql.SQL("SELECT max({}) FROM {}").format(
                    sql.Identifier(column), _qualified(tbl_schema, tbl_name)
                )
            ).fetchone()[0]
            entry["max_owned_value"] = int(max_value) if max_value is not None else None
        result[f"{seq_schema}.{seq_name}"] = entry
    return result


def snapshot_fingerprint(conn: psycopg.Connection, schemas: Sequence[str] = DEFAULT_SCHEMAS) -> dict[str, Any]:
    """Fingerprint every table in ``schemas``: rows, digests, and safety structure.

    Must be called as the table owner or a superuser (not ``oc_crm_runtime``); see
    the module docstring. When ``conn`` already has an open transaction (for example
    a ``REPEATABLE READ`` snapshot shared with ``pg_dump``) the fingerprint is taken
    inside it, so it describes exactly that snapshot. The result is JSON-serializable.
    """
    schema_list = validate_schemas(schemas)
    with _read_scope(conn):
        _apply_canonical_settings(conn)
        present = {
            row[0]
            for row in conn.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)", (schema_list,)
            ).fetchall()
        }
        server_version = conn.execute("SHOW server_version").fetchone()[0]
        tables: dict[str, dict[str, Any]] = {}
        for info in _discover_tables(conn, schema_list):
            columns = _table_columns(conn, info["oid"])
            pk = _primary_key(conn, info["oid"])
            count, digest = _content_digest(conn, info["schema"], info["table"], _order_by(columns, pk))
            tables[f"{info['schema']}.{info['table']}"] = {
                "row_count": count,
                "content_sha256": digest,
                "primary_key": pk,
                "columns": [
                    {k: v for k, v in col.items() if k != "collatable"} for col in columns
                ],
                "rls_enabled": info["rls_enabled"],
                "rls_forced": info["rls_forced"],
                "acl": info["acl"],
                "policies": _policies(conn, info["oid"]),
                "triggers": _triggers(conn, info["oid"]),
                "constraints": _constraints(conn, info["oid"]),
                "indexes": _indexes(conn, info["oid"]),
            }
        return {
            "fingerprint_version": FINGERPRINT_VERSION,
            "database": conn.info.dbname,
            "server_version": server_version,
            "taken_at": datetime.now(timezone.utc).isoformat(),
            "schemas": schema_list,
            "schemas_present": sorted(present),
            "tables": tables,
            "functions": _functions(conn, schema_list),
            "sequences": _sequences(conn, schema_list),
        }


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------
def _discrepancy(category: str, obj: str, message: str, *, severity: str = "error", **details: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {"category": category, "object": obj, "severity": severity, "message": message}
    if details:
        entry["details"] = details
    return entry


def _compare_named(
    out: list[dict[str, Any]],
    category: str,
    label: str,
    table: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    for name in sorted(before.keys() - after.keys()):
        out.append(_discrepancy(category, table, f"table {table}: {label} {name} is missing after restore"))
    for name in sorted(after.keys() - before.keys()):
        out.append(
            _discrepancy(category, table, f"table {table}: {label} {name} exists after restore but not in backup source")
        )
    for name in sorted(before.keys() & after.keys()):
        if before[name] != after[name]:
            out.append(
                _discrepancy(
                    category,
                    table,
                    f"table {table}: {label} {name} differs after restore",
                    source=before[name],
                    restored=after[name],
                )
            )


def compare_fingerprints(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    """Return human-readable, admin-actionable discrepancies (empty list = identical).

    ``before`` is the backup source; ``after`` is the restored database. Sequence
    positions are compared monotonically: the restored sequence must not be behind
    the source (and must be ahead of every restored id), otherwise ids would be
    reissued.
    """
    out: list[dict[str, Any]] = []
    for schema in before.get("schemas_present", []):
        if schema not in after.get("schemas_present", []):
            out.append(_discrepancy("schema", schema, f"schema {schema}: missing after restore"))

    tables_before: dict[str, Any] = before.get("tables", {})
    tables_after: dict[str, Any] = after.get("tables", {})
    for name in sorted(tables_before.keys() - tables_after.keys()):
        rows = tables_before[name]["row_count"]
        out.append(
            _discrepancy(
                "table", name, f"table {name}: missing after restore (backup source has {rows} rows)", source_rows=rows
            )
        )
    for name in sorted(tables_after.keys() - tables_before.keys()):
        out.append(
            _discrepancy(
                "table", name, f"table {name}: exists after restore but not in backup source", severity="warning"
            )
        )

    for name in sorted(tables_before.keys() & tables_after.keys()):
        b, a = tables_before[name], tables_after[name]
        if b["row_count"] != a["row_count"]:
            out.append(
                _discrepancy(
                    "row_count",
                    name,
                    f"table {name}: {b['row_count']} rows in backup source, {a['row_count']} after restore",
                    source_rows=b["row_count"],
                    restored_rows=a["row_count"],
                )
            )
        elif b["content_sha256"] != a["content_sha256"]:
            out.append(
                _discrepancy(
                    "row_content",
                    name,
                    f"table {name}: row contents differ after restore although both have "
                    f"{b['row_count']} rows (digest {b['content_sha256'][:12]} in backup source, "
                    f"{a['content_sha256'][:12]} after restore)",
                    source_sha256=b["content_sha256"],
                    restored_sha256=a["content_sha256"],
                )
            )
        if b["columns"] != a["columns"]:
            out.append(
                _discrepancy(
                    "columns", name, f"table {name}: column definitions differ after restore",
                    source=b["columns"], restored=a["columns"],
                )
            )
        if b["rls_enabled"] and not a["rls_enabled"]:
            out.append(
                _discrepancy(
                    "rls", name,
                    f"table {name}: row-level security is ENABLED in backup source but DISABLED after restore "
                    "-- tenant isolation is lost for this table",
                )
            )
        elif a["rls_enabled"] != b["rls_enabled"]:
            out.append(
                _discrepancy("rls", name, f"table {name}: row-level security is enabled after restore but not in backup source")
            )
        if a["rls_forced"] != b["rls_forced"]:
            out.append(
                _discrepancy(
                    "rls", name,
                    f"table {name}: FORCE ROW LEVEL SECURITY is {'on' if b['rls_forced'] else 'off'} in backup source, "
                    f"{'on' if a['rls_forced'] else 'off'} after restore",
                )
            )
        if b["acl"] != a["acl"]:
            out.append(
                _discrepancy(
                    "privileges", name, f"table {name}: privileges (GRANTs) differ after restore",
                    source=b["acl"], restored=a["acl"],
                )
            )
        _compare_named(out, "policy", "policy", name, b["policies"], a["policies"])
        for trig in sorted(b["triggers"].keys() & a["triggers"].keys()):
            if b["triggers"][trig]["enabled"] != "D" and a["triggers"][trig]["enabled"] == "D":
                out.append(
                    _discrepancy(
                        "trigger", name,
                        f"table {name}: trigger {trig} is DISABLED after restore (enabled in backup source) "
                        "-- its guard (for example audit immutability) no longer runs",
                    )
                )
            elif b["triggers"][trig]["enabled"] != a["triggers"][trig]["enabled"]:
                out.append(
                    _discrepancy(
                        "trigger", name,
                        f"table {name}: trigger {trig} firing mode is {b['triggers'][trig]['enabled']!r} in backup "
                        f"source, {a['triggers'][trig]['enabled']!r} after restore",
                    )
                )
        _compare_named(
            out, "trigger", "trigger", name,
            {k: v["definition"] for k, v in b["triggers"].items()},
            {k: v["definition"] for k, v in a["triggers"].items()},
        )
        for con in sorted(b["constraints"].keys() & a["constraints"].keys()):
            if b["constraints"][con]["validated"] and not a["constraints"][con]["validated"]:
                out.append(
                    _discrepancy(
                        "constraint", name,
                        f"table {name}: constraint {con} is VALID in backup source but NOT VALID after restore",
                    )
                )
        _compare_named(
            out, "constraint", "constraint", name,
            {k: {"type": v["type"], "definition": v["definition"]} for k, v in b["constraints"].items()},
            {k: {"type": v["type"], "definition": v["definition"]} for k, v in a["constraints"].items()},
        )
        _compare_named(out, "index", "index", name, b["indexes"], a["indexes"])

    fb, fa = before.get("functions", {}), after.get("functions", {})
    for fn in sorted(fb.keys() - fa.keys()):
        out.append(_discrepancy("function", fn, f"function {fn}: missing after restore"))
    for fn in sorted(fb.keys() & fa.keys()):
        if fb[fn] != fa[fn]:
            out.append(_discrepancy("function", fn, f"function {fn}: definition differs after restore"))
    for fn in sorted(fa.keys() - fb.keys()):
        out.append(_discrepancy("function", fn, f"function {fn}: exists after restore but not in backup source", severity="warning"))

    sb, sa = before.get("sequences", {}), after.get("sequences", {})
    for seq in sorted(sb.keys() - sa.keys()):
        out.append(_discrepancy("sequence", seq, f"sequence {seq}: missing after restore"))
    for seq in sorted(sb.keys() & sa.keys()):
        src, dst = sb[seq], sa[seq]
        if dst["next_value"] < src["next_value"]:
            out.append(
                _discrepancy(
                    "sequence", seq,
                    f"sequence {seq}: next value is {src['next_value']} in backup source but {dst['next_value']} "
                    f"after restore -- ids {dst['next_value']}..{src['next_value'] - 1} would be reissued",
                    source=src, restored=dst,
                )
            )
    for seq, dst in sorted(sa.items()):
        max_owned = dst.get("max_owned_value")
        if max_owned is not None and dst["next_value"] <= max_owned:
            out.append(
                _discrepancy(
                    "sequence", seq,
                    f"sequence {seq}: next value {dst['next_value']} after restore does not exceed the highest "
                    f"existing {dst['owned_by']} ({max_owned}) -- new rows would collide with restored ids",
                    restored=dst,
                )
            )
    return out


# ---------------------------------------------------------------------------
# Row-level localization of content discrepancies
# ---------------------------------------------------------------------------
def _row_hashes(conn: psycopg.Connection, table: str, pk: list[str]) -> dict[str, str]:
    schema, name = table.split(".", 1)
    key_expr = sql.SQL("json_build_array({})::text").format(
        sql.SQL(", ").join(sql.SQL("t.{}").format(sql.Identifier(col)) for col in pk)
    )
    query = sql.SQL("SELECT {}, md5(row_to_json(t)::text) FROM {} AS t").format(key_expr, _qualified(schema, name))
    result: dict[str, str] = {}
    with conn.cursor(name=f"oc_fp_rows_{uuid.uuid4().hex[:12]}") as cur:
        cur.itersize = 5000
        cur.execute(query)
        for key, row_md5 in cur:
            result[key] = row_md5
    return result


def _format_key(pk: list[str], key_json: str) -> str:
    try:
        values = json.loads(key_json)
    except ValueError:
        return key_json
    return ", ".join(f"{col}={value}" for col, value in zip(pk, values))


def localize_row_differences(
    source_conn: psycopg.Connection,
    restored_conn: psycopg.Connection,
    table: str,
    pk: list[str],
    *,
    limit: int = _ROW_EXAMPLES,
) -> dict[str, Any]:
    """Name the primary keys of rows missing, extra, or changed after restore."""
    with _read_scope(source_conn):
        _apply_canonical_settings(source_conn)
        src = _row_hashes(source_conn, table, pk)
    with _read_scope(restored_conn):
        _apply_canonical_settings(restored_conn)
        dst = _row_hashes(restored_conn, table, pk)
    missing = sorted(src.keys() - dst.keys())
    extra = sorted(dst.keys() - src.keys())
    changed = sorted(k for k in src.keys() & dst.keys() if src[k] != dst[k])
    return {
        "missing_after_restore": [_format_key(pk, k) for k in missing[:limit]],
        "extra_after_restore": [_format_key(pk, k) for k in extra[:limit]],
        "changed_after_restore": [_format_key(pk, k) for k in changed[:limit]],
        "missing_count": len(missing),
        "extra_count": len(extra),
        "changed_count": len(changed),
    }


def _annotate_row_discrepancies(
    discrepancies: list[dict[str, Any]],
    before: dict[str, Any],
    source_conn: psycopg.Connection,
    restored_conn: psycopg.Connection,
) -> None:
    for entry in discrepancies:
        if entry["category"] not in {"row_count", "row_content"}:
            continue
        info = before["tables"].get(entry["object"], {})
        pk = info.get("primary_key") or []
        if not pk or info.get("row_count", 0) > _ROW_LOCALIZE_LIMIT:
            continue
        rows = localize_row_differences(source_conn, restored_conn, entry["object"], pk)
        entry.setdefault("details", {})["rows"] = rows
        parts = []
        for label, key in (("missing after restore", "missing_after_restore"),
                           ("extra after restore", "extra_after_restore"),
                           ("changed after restore", "changed_after_restore")):
            if rows[key]:
                shown = "; ".join(rows[key])
                more = rows[key.replace("_after_restore", "_count")] - len(rows[key])
                parts.append(f"{label}: {shown}" + (f" (+{more} more)" if more > 0 else ""))
        if parts:
            entry["message"] += " [" + " | ".join(parts) + "]"


# ---------------------------------------------------------------------------
# Functional checks on the restored database
# ---------------------------------------------------------------------------
def _tenant_tables(fingerprint: dict[str, Any]) -> dict[str, str]:
    """Map RLS-protected tables to the tenant column named in their runtime policy."""
    result: dict[str, str] = {}
    for name, info in fingerprint["tables"].items():
        for policy in info["policies"].values():
            if RUNTIME_ROLE not in policy["roles"] or not policy["using"]:
                continue
            match = _TENANT_QUAL.match(policy["using"].strip())
            if match:
                result[name] = match.group(1)
                break
    return result


def check_restored_roles(conn: psycopg.Connection, fingerprint: dict[str, Any]) -> dict[str, Any]:
    referenced = sorted(
        {role for info in fingerprint["tables"].values() for p in info["policies"].values() for role in p["roles"]}
        - {"public"}
    )
    existing = {
        row[0] for row in conn.execute("SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)", (referenced,)).fetchall()
    }
    runtime_policies = sorted(
        f"{table}:{name}"
        for table, info in fingerprint["tables"].items()
        for name, p in info["policies"].items()
        if RUNTIME_ROLE in p["roles"]
    )
    missing = sorted(set(referenced) - existing)
    return {
        "roles_referenced_by_policies": referenced,
        "missing_roles": missing,
        "runtime_role": RUNTIME_ROLE,
        "policies_bound_to_runtime_role": len(runtime_policies),
        "status": "pass" if not missing else "fail",
    }


def check_restored_isolation(
    conn: psycopg.Connection,
    fingerprint: dict[str, Any],
    *,
    organization_ids: Sequence[int] | None = None,
    org_limit: int = 20,
) -> dict[str, Any]:
    """Exercise RLS in the restored DB via the application's own tenant_transaction.

    * default deny: under ``oc_crm_runtime`` with no tenant, every protected table
      the role can read shows zero rows;
    * per tenant: for each sampled organization, the runtime role sees exactly the
      rows whose tenant column equals that organization (compared with an owner-level
      count) and never a row of another tenant.
    """
    failures: list[str] = []
    tenant_tables = _tenant_tables(fingerprint)
    readable = [
        t for t in sorted(tenant_tables)
        if conn.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", (RUNTIME_ROLE, t)).fetchone()[0]
    ]
    if organization_ids is None:
        org_table = "oc_constituent.organizations"
        if org_table in fingerprint["tables"]:
            organization_ids = [
                int(row[0])
                for row in conn.execute(
                    "SELECT id FROM oc_constituent.organizations ORDER BY id LIMIT %s", (org_limit,)
                ).fetchall()
            ]
        else:
            organization_ids = []

    def as_table(name: str) -> sql.Composed:
        schema, table = name.split(".", 1)
        return _qualified(schema, table)

    # Default deny: runtime role, no tenant setting.
    default_deny: dict[str, int] = {}
    with conn.transaction():
        conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(RUNTIME_ROLE)))
        conn.execute("SELECT set_config('oc.crm_organization_id', '', true)")
        for name in readable:
            visible = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(as_table(name))).fetchone()[0]
            default_deny[name] = int(visible)
            if visible:
                failures.append(
                    f"table {name}: {visible} rows visible to {RUNTIME_ROLE} with NO tenant set (expected 0) "
                    "-- default-deny isolation is broken in the restored database"
                )

    per_org: dict[str, dict[str, Any]] = {}
    for org_id in organization_ids:
        expected: dict[str, int] = {}
        with conn.transaction():
            conn.execute("SELECT set_config('row_security', 'off', true)")
            for name in readable:
                expected[name] = int(
                    conn.execute(
                        sql.SQL("SELECT count(*) FROM {} WHERE {} = %s").format(
                            as_table(name), sql.Identifier(tenant_tables[name])
                        ),
                        (org_id,),
                    ).fetchone()[0]
                )
        observed: dict[str, dict[str, int]] = {}
        with tenant_transaction(org_id, connect=lambda: conn, connection=conn) as cur:
            for name in readable:
                cur.execute(
                    sql.SQL("SELECT count(*) AS visible, count(*) FILTER (WHERE {} IS DISTINCT FROM %s) AS foreign_rows FROM {}").format(
                        sql.Identifier(tenant_tables[name]), as_table(name)
                    ),
                    (org_id,),
                )
                row = cur.fetchone()
                observed[name] = {"visible": int(row["visible"]), "foreign_rows": int(row["foreign_rows"])}
        for name in readable:
            obs = observed[name]
            if obs["foreign_rows"]:
                failures.append(
                    f"table {name}: organization {org_id} can see {obs['foreign_rows']} rows belonging to other "
                    "organizations after restore -- cross-tenant leak"
                )
            if obs["visible"] - obs["foreign_rows"] != expected[name]:
                failures.append(
                    f"table {name}: organization {org_id} sees {obs['visible'] - obs['foreign_rows']} of its own rows "
                    f"under {RUNTIME_ROLE}, but {expected[name]} exist after restore -- tenant policy does not match data"
                )
        per_org[str(org_id)] = {
            name: {"expected": expected[name], **observed[name]} for name in readable
        }

    if failures:
        status = "fail"
    elif len(organization_ids) >= 2:
        status = "pass"
    else:
        status = "insufficient_data"
    return {
        "status": status,
        "tenant_tables_checked": readable,
        "tenant_columns": {name: tenant_tables[name] for name in readable},
        "organizations_checked": list(organization_ids),
        "default_deny_visible_rows": default_deny,
        "per_organization": per_org,
        "failures": failures,
        "note": (
            "Isolation between tenants is only proven when at least two organizations exist in the "
            "restored data." if status == "insufficient_data" else None
        ),
    }


def check_append_only_guards(
    conn: psycopg.Connection, tables: Sequence[str] = DEFAULT_APPEND_ONLY_TABLES
) -> dict[str, Any]:
    """Prove UPDATE is still rejected on append-only tables (scratch DB only; rolled back)."""
    results: dict[str, str] = {}
    failures: list[str] = []
    for name in tables:
        schema, table = name.split(".", 1)
        exists = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (name,)).fetchone()[0]
        if not exists:
            results[name] = "absent"
            continue
        first_col = conn.execute(
            "SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass AND attnum > 0 "
            "AND NOT attisdropped ORDER BY attnum LIMIT 1",
            (name,),
        ).fetchone()[0]
        has_row = conn.execute(sql.SQL("SELECT EXISTS (SELECT 1 FROM {})").format(_qualified(schema, table))).fetchone()[0]
        if not has_row:
            results[name] = "not_exercised_empty_table"
            continue
        try:
            with conn.transaction():
                conn.execute(
                    sql.SQL("UPDATE {tbl} SET {col} = {col} WHERE ctid = (SELECT ctid FROM {tbl} LIMIT 1)").format(
                        tbl=_qualified(schema, table), col=sql.Identifier(first_col)
                    )
                )
                raise _RolledBack()
        except _RolledBack:
            results[name] = "fail_update_accepted"
            failures.append(f"table {name}: UPDATE was accepted after restore -- append-only guard is not active")
        except psycopg.Error as exc:
            message = (exc.diag.message_primary or str(exc)).strip()
            results[name] = f"rejected: {message}"
    return {"status": "fail" if failures else "pass", "tables": results, "failures": failures}


class _RolledBack(Exception):
    """Raised inside a probe transaction to force its rollback."""


# ---------------------------------------------------------------------------
# pg_dump / pg_restore
# ---------------------------------------------------------------------------
def find_pg_binary(name: str, env_var: str | None = None) -> str | None:
    """Locate a PostgreSQL client binary: env override, newest versioned dir, then PATH."""
    if env_var and os.environ.get(env_var):
        candidate = os.environ[env_var]
        return candidate if os.path.isfile(candidate) and os.access(candidate, os.X_OK) else None
    versioned = []
    for path in glob.glob(f"/usr/lib/postgresql/*/bin/{name}"):
        try:
            versioned.append((int(Path(path).parts[-3]), path))
        except ValueError:
            continue
    if versioned:
        return max(versioned)[1]
    return shutil.which(name)


def _binary_major_version(binary: str) -> tuple[int | None, str]:
    output = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False).stdout.strip()
    match = re.search(r"(\d+)(?:\.\d+)?", output)
    return (int(match.group(1)) if match else None), output


def _run_tool(args: list[str], env: dict[str, str], secrets: Iterable[str]) -> None:
    proc = subprocess.run(args, env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = redact_text(proc.stderr.strip(), secrets)[-4000:]
        raise RestoreDrillError(f"{Path(args[0]).name} exited with {proc.returncode}: {stderr}")


class RestoreDrillError(RuntimeError):
    """The drill could not run to completion (distinct from a completed, failing drill)."""


def _server_major(conn: psycopg.Connection) -> int:
    return int(conn.info.server_version) // 10000


def run_backup_restore_drill(
    source_dsn: str,
    scratch_admin_dsn: str | None = None,
    schemas: Sequence[str] = DEFAULT_SCHEMAS,
    pg_dump_bin: str | None = None,
    pg_restore_bin: str | None = None,
    *,
    keep: bool = False,
    dump_path: str | os.PathLike[str] | None = None,
    isolation_organization_ids: Sequence[int] | None = None,
    isolation_org_limit: int = 20,
    append_only_tables: Sequence[str] = DEFAULT_APPEND_ONLY_TABLES,
    after_restore_hook: Callable[[psycopg.Connection], None] | None = None,
) -> dict[str, Any]:
    """Dump ``schemas`` from the source, restore into a fresh scratch DB, and verify.

    ``scratch_admin_dsn`` must be able to ``CREATE DATABASE`` (defaults to the source
    DSN's cluster). ``after_restore_hook`` exists for negative tests: it receives an
    autocommit connection to the scratch DB before the restored fingerprint is taken.
    Returns a JSON-serializable report; ``report["pass"]`` is the verdict.
    """
    schema_list = validate_schemas(schemas)
    source_dsn = _normalize_dsn(source_dsn)
    admin_dsn = _normalize_dsn(scratch_admin_dsn or source_dsn)
    secrets = [s for s in (_dsn_password(source_dsn), _dsn_password(admin_dsn)) if s]
    pg_dump_bin = pg_dump_bin or find_pg_binary("pg_dump", "PG_DUMP_BIN")
    pg_restore_bin = pg_restore_bin or find_pg_binary("pg_restore", "PG_RESTORE_BIN")
    if not pg_dump_bin or not pg_restore_bin:
        raise RestoreDrillError("pg_dump/pg_restore not found (set PG_DUMP_BIN and PG_RESTORE_BIN)")

    scratch_db = f"{SCRATCH_PREFIX}{uuid.uuid4().hex}"
    timings: dict[str, float] = {}
    report: dict[str, Any] = {
        "drill": "OC-CRM-BACKUP-RESTORE-001",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "source": redact_dsn(source_dsn),
        "scratch_admin": redact_dsn(admin_dsn),
        "scratch_database": scratch_db,
        "schemas": schema_list,
        "schemas_requested": list(schema_list),
        "dump_format": "custom (-Fc)",
        "roles_caveat": (
            "Roles (including oc_crm_runtime) are cluster-level and are not in pg_dump output; "
            "the target cluster must already have them. Verified below under checks.roles."
        ),
        "pass": False,
    }

    def clock(step: str, started: float) -> None:
        timings[step] = round(time.monotonic() - started, 3)

    workdir = tempfile.mkdtemp(prefix="oc_crm_drill_")
    dump_file = Path(dump_path) if dump_path else Path(workdir) / "crm.dump"
    scratch_created = False
    admin_conn: psycopg.Connection | None = None
    try:
        dump_major, dump_version = _binary_major_version(pg_dump_bin)
        restore_major, restore_version = _binary_major_version(pg_restore_bin)
        report["pg_dump_version"] = dump_version
        report["pg_restore_version"] = restore_version

        with psycopg.connect(source_dsn) as source_conn:
            server_major = _server_major(source_conn)
            if dump_major is not None and dump_major < server_major:
                raise RestoreDrillError(
                    f"pg_dump major version {dump_major} is older than source server {server_major}; "
                    "install a matching client (e.g. postgresql-client-16)"
                )
            present = {
                row[0]
                for row in source_conn.execute(
                    "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)", (schema_list,)
                ).fetchall()
            }
            source_conn.rollback()
            report["schemas_absent"] = [schema for schema in schema_list if schema not in present]
            schema_list = [schema for schema in schema_list if schema in present]
            if not schema_list:
                raise RestoreDrillError("none of the requested schemas exist in the source database")
            report["schemas"] = schema_list
            source_conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
            source_conn.read_only = True
            snapshot_id = source_conn.execute("SELECT pg_export_snapshot()").fetchone()[0]

            started = time.monotonic()
            before = snapshot_fingerprint(source_conn, schema_list)
            clock("fingerprint_source_seconds", started)

            conninfo, env = _client_conninfo(source_dsn)
            started = time.monotonic()
            dump_args = [pg_dump_bin, "--format=custom", "--no-password", f"--snapshot={snapshot_id}",
                         f"--file={dump_file}"]
            dump_args += [f"--schema={schema}" for schema in schema_list]
            dump_args.append(f"--dbname={conninfo}")
            _run_tool(dump_args, env, secrets)
            clock("pg_dump_seconds", started)
            report["dump_bytes"] = dump_file.stat().st_size

            admin_conn = psycopg.connect(admin_dsn, autocommit=True)
            if restore_major is not None and restore_major < _server_major(admin_conn):
                raise RestoreDrillError("pg_restore is older than the scratch server; install a matching client")
            started = time.monotonic()
            admin_conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(scratch_db)))
            scratch_created = True
            clock("create_scratch_seconds", started)

            scratch_dsn = _dsn_with_dbname(admin_dsn, scratch_db)
            restore_conninfo, restore_env = _client_conninfo(admin_dsn, dbname=scratch_db)
            started = time.monotonic()
            _run_tool(
                [pg_restore_bin, "--exit-on-error", "--single-transaction", "--no-password",
                 f"--dbname={restore_conninfo}", str(dump_file)],
                restore_env,
                secrets,
            )
            clock("pg_restore_seconds", started)

            with psycopg.connect(scratch_dsn, autocommit=True) as scratch_conn:
                if after_restore_hook is not None:
                    after_restore_hook(scratch_conn)
                started = time.monotonic()
                after = snapshot_fingerprint(scratch_conn, schema_list)
                clock("fingerprint_restored_seconds", started)

                discrepancies = compare_fingerprints(before, after)
                _annotate_row_discrepancies(discrepancies, before, source_conn, scratch_conn)
                source_conn.rollback()  # release the exported snapshot

                started = time.monotonic()
                roles = check_restored_roles(scratch_conn, after)
                isolation = check_restored_isolation(
                    scratch_conn, after,
                    organization_ids=isolation_organization_ids, org_limit=isolation_org_limit,
                )
                guards = check_append_only_guards(scratch_conn, append_only_tables)
                clock("functional_checks_seconds", started)

        errors = [d for d in discrepancies if d["severity"] == "error"]
        tables_report = {
            name: {
                "source_rows": info["row_count"],
                "restored_rows": after["tables"].get(name, {}).get("row_count"),
                "source_sha256": info["content_sha256"],
                "restored_sha256": after["tables"].get(name, {}).get("content_sha256"),
                "match": (
                    name in after["tables"]
                    and after["tables"][name]["row_count"] == info["row_count"]
                    and after["tables"][name]["content_sha256"] == info["content_sha256"]
                ),
            }
            for name, info in before["tables"].items()
        }
        report.update(
            {
                "source_server_version": before["server_version"],
                "tables": tables_report,
                "table_count": len(tables_report),
                "total_source_rows": sum(t["source_rows"] for t in tables_report.values()),
                "sequences": {name: {"source": seq, "restored": after["sequences"].get(name)}
                              for name, seq in before["sequences"].items()},
                "discrepancies": discrepancies,
                "checks": {"roles": roles, "isolation": isolation, "append_only_guards": guards},
            }
        )
        report["pass"] = (
            not errors
            and roles["status"] == "pass"
            and isolation["status"] in {"pass", "insufficient_data"}
            and guards["status"] == "pass"
        )
        report["isolation_verified_between_tenants"] = isolation["status"] == "pass"
        report["warnings"] = [
            f"schema {schema}: requested but absent from the backup source (not dumped or verified)"
            for schema in report["schemas_absent"]
        ] + [d["message"] for d in discrepancies if d["severity"] != "error"]
        if isolation["status"] == "insufficient_data":
            report["warnings"].append(isolation["note"])
        return report
    finally:
        if scratch_created and admin_conn is not None:
            if keep:
                report["scratch_database_kept"] = True
            else:
                started = time.monotonic()
                try:
                    admin_conn.execute(
                        sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(scratch_db))
                    )
                    report["scratch_database_dropped"] = True
                except psycopg.Error as exc:
                    report["scratch_database_dropped"] = False
                    report["scratch_drop_error"] = redact_text(str(exc), secrets)
                clock("drop_scratch_seconds", started)
        if admin_conn is not None:
            admin_conn.close()
        if dump_path is None:
            shutil.rmtree(workdir, ignore_errors=True)
        else:
            report["dump_path"] = str(dump_file)
            shutil.rmtree(workdir, ignore_errors=True)
        report["timings"] = timings
        report["finished_at"] = datetime.now(timezone.utc).isoformat()


def drop_scratch_database(admin_dsn: str, name: str) -> None:
    """Drop a kept scratch database. Refuses any name without the drill prefix."""
    if not name.startswith(SCRATCH_PREFIX) or not _IDENTIFIER.match(name):
        raise ValueError(f"refusing to drop {name!r}: not a restore-drill scratch database")
    with psycopg.connect(_normalize_dsn(admin_dsn), autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
