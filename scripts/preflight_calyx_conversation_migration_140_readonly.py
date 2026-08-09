from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parents[1]
M140 = ROOT / "migrations/140_calyx_conversation_sessions.sql"
EXPECTED_M140_BLOB = "f572ba9aa1a3bade4dfe9d1e1faf0dbfb8a57baf"
REPORT = Path(os.environ.get("M140_PRODUCTION_PREFLIGHT_REPORT", "migration-140-production-readonly-preflight.json"))


def blob_sha(path: Path) -> str:
    return subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()


def relation(conn, name: str) -> str | None:
    return conn.execute("SELECT to_regclass(%s)::text", (name,)).fetchone()[0]


def columns(conn, table: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT column_name, data_type, udt_name, is_nullable, column_default
           FROM information_schema.columns
           WHERE table_schema='research_station' AND table_name=%s
           ORDER BY ordinal_position""", (table,)
    ).fetchall()
    return [dict(zip(("column_name","data_type","udt_name","is_nullable","column_default"), row)) for row in rows]


def constraints(conn, table: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """SELECT c.conname, c.contype, pg_get_constraintdef(c.oid)
           FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
           JOIN pg_namespace n ON n.oid=t.relnamespace
           WHERE n.nspname='research_station' AND t.relname=%s ORDER BY c.conname""", (table,)
    ).fetchall()
    return [{"name": r[0], "type": r[1], "definition": r[2]} for r in rows]


def indexes(conn, table: str) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='research_station' AND tablename=%s ORDER BY indexname", (table,)
    ).fetchall()
    return [{"name": r[0], "definition": r[1]} for r in rows]


def triggers(conn, table: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """SELECT t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t
           JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE NOT t.tgisinternal AND n.nspname='research_station' AND c.relname=%s ORDER BY t.tgname""", (table,)
    ).fetchall()
    return [{"name": r[0], "definition": r[1]} for r in rows]


def privileges(conn, table: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """SELECT grantee, privilege_type FROM information_schema.table_privileges
           WHERE table_schema='research_station' AND table_name=%s ORDER BY grantee, privilege_type""", (table,)
    ).fetchall()
    return [{"grantee": r[0], "privilege": r[1]} for r in rows]


def main() -> None:
    identity = {
        "git_blob_sha": blob_sha(M140),
        "expected_git_blob_sha": EXPECTED_M140_BLOB,
        "sha256": hashlib.sha256(M140.read_bytes()).hexdigest(),
    }
    if identity["git_blob_sha"] != EXPECTED_M140_BLOB:
        raise SystemExit("migration 140 identity drift")
    url = os.environ.get("DATABASE_URL", "").strip()
    receipt: dict[str, Any] = {
        "mode": "PRODUCTION_READ_ONLY_PREFLIGHT",
        "migration_identity": identity,
        "production_mutation_authorized": False,
        "production_mutation_attempted": False,
    }
    if not url:
        receipt.update({"status": "BLOCKED", "blocker": "DATABASE_URL_SECRET_UNAVAILABLE"})
        REPORT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return

    with psycopg.connect(url, options="-c default_transaction_read_only=on") as conn:
        with conn.transaction():
            read_only = conn.execute("SHOW transaction_read_only").fetchone()[0]
            if read_only != "on":
                raise RuntimeError(f"read-only guard failed: {read_only}")
            receipt["postgresql_version"] = conn.execute("SHOW server_version").fetchone()[0]
            receipt["server_version_num"] = conn.execute("SHOW server_version_num").fetchone()[0]
            receipt["current_user"] = conn.execute("SELECT current_user").fetchone()[0]
            receipt["session_user"] = conn.execute("SELECT session_user").fetchone()[0]
            receipt["read_only_guard"] = read_only
            receipt["pgcrypto"] = conn.execute("SELECT extversion FROM pg_extension WHERE extname='pgcrypto'").fetchone()
            receipt["research_station_schema"] = bool(conn.execute("SELECT 1 FROM pg_namespace WHERE nspname='research_station'").fetchone())
            objects: dict[str, Any] = {}
            for table in ("projects", "conversation_sessions", "conversation_messages"):
                exists = relation(conn, f"research_station.{table}") is not None
                objects[table] = {
                    "exists": exists,
                    "columns": columns(conn, table) if exists else [],
                    "constraints": constraints(conn, table) if exists else [],
                    "indexes": indexes(conn, table) if exists else [],
                    "triggers": triggers(conn, table) if exists else [],
                    "privileges": privileges(conn, table) if exists else [],
                }
            receipt["objects"] = objects
            receipt["reject_function"] = conn.execute(
                "SELECT to_regprocedure('research_station.reject_conversation_message_mutation()')::text"
            ).fetchone()[0]
            receipt["schema_owner"] = conn.execute("SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='research_station'").fetchone()
            receipt["relevant_roles"] = [r[0] for r in conn.execute(
                "SELECT DISTINCT grantee FROM information_schema.table_privileges WHERE table_schema='research_station' ORDER BY grantee"
            ).fetchall()]
            projects = objects["projects"]
            receipt["migration_101_prerequisite_compatible"] = bool(
                projects["exists"]
                and any(c["column_name"] == "project_id" and c["data_type"] == "uuid" for c in projects["columns"])
                and any("PRIMARY KEY (project_id)" in c["definition"] for c in projects["constraints"])
            )
            target_exists = [objects[x]["exists"] for x in ("conversation_sessions", "conversation_messages")]
            receipt["target_state"] = "ABSENT" if target_exists == [False, False] else (
                "BOTH_PRESENT" if target_exists == [True, True] else "PARTIAL"
            )
            receipt["production_mutation_attempted"] = False
            receipt["status"] = "VERIFIED_READ_ONLY_IN_PRODUCTION"

    REPORT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
