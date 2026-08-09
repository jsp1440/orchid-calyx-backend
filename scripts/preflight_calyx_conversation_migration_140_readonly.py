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
IMMUTABLE_TRIGGER_NAME = "rs_conversation_messages_immutable"
IMMUTABLE_TRIGGER_RELATION = ("research_station", "conversation_messages")

EXPECTED_TARGET_COLUMNS: dict[str, dict[str, dict[str, Any]]] = {
    "conversation_sessions": {
        "conversation_id": {"type": "uuid", "nullable": "NO", "default": "gen_random_uuid()"},
        "owner_subject": {"type": "text", "nullable": "NO", "default": None},
        "project_id": {"type": "uuid", "nullable": "YES", "default": None},
        "title": {"type": "text", "nullable": "NO", "default": "Calyx conversation"},
        "active_taxon_id": {"type": "text", "nullable": "YES", "default": None},
        "active_document_id": {"type": "text", "nullable": "YES", "default": None},
        "created_at": {"type": "timestamp with time zone", "nullable": "NO", "default": "now()"},
        "updated_at": {"type": "timestamp with time zone", "nullable": "NO", "default": "now()"},
        "archived_at": {"type": "timestamp with time zone", "nullable": "YES", "default": None},
        "version": {"type": "integer", "nullable": "NO", "default": "1"},
    },
    "conversation_messages": {
        "message_id": {"type": "uuid", "nullable": "NO", "default": "gen_random_uuid()"},
        "conversation_id": {"type": "uuid", "nullable": "NO", "default": None},
        "owner_subject": {"type": "text", "nullable": "NO", "default": None},
        "role": {"type": "text", "nullable": "NO", "default": None},
        "content": {"type": "text", "nullable": "NO", "default": None},
        "epistemic_status": {"type": "text", "nullable": "YES", "default": None},
        "context_json": {"type": "jsonb", "nullable": "NO", "default": "{}"},
        "source_refs_json": {"type": "jsonb", "nullable": "NO", "default": "[]"},
        "tool_trace_json": {"type": "jsonb", "nullable": "NO", "default": "[]"},
        "data_status": {"type": "text", "nullable": "NO", "default": "CONVERSATION_CONTEXT"},
        "evidence_authority": {"type": "boolean", "nullable": "NO", "default": "false"},
        "scientific_publication_authorized": {"type": "boolean", "nullable": "NO", "default": "false"},
        "knowledge_graph_mutation_authorized": {"type": "boolean", "nullable": "NO", "default": "false"},
        "created_at": {"type": "timestamp with time zone", "nullable": "NO", "default": "now()"},
    },
}


def blob_sha(path: Path) -> str:
    return subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()


def relation(conn, name: str) -> str | None:
    return conn.execute("SELECT to_regclass(%s)::text", (name,)).fetchone()[0]


def columns(conn, table: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT column_name, data_type, udt_name, is_nullable, column_default
           FROM information_schema.columns
           WHERE table_schema='research_station' AND table_name=%s ORDER BY ordinal_position""",
        (table,),
    ).fetchall()
    names = ("column_name", "data_type", "udt_name", "is_nullable", "column_default")
    return [dict(zip(names, row)) for row in rows]


def constraints(conn, table: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """SELECT c.conname, c.contype, pg_get_constraintdef(c.oid)
           FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
           JOIN pg_namespace n ON n.oid=t.relnamespace
           WHERE n.nspname='research_station' AND t.relname=%s ORDER BY c.conname""",
        (table,),
    ).fetchall()
    return [{"name": row[0], "type": row[1], "definition": row[2]} for row in rows]


def indexes(conn, table: str) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='research_station' AND tablename=%s ORDER BY indexname",
        (table,),
    ).fetchall()
    return [{"name": row[0], "definition": row[1]} for row in rows]


def triggers(conn, table: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """SELECT t.tgname, pg_get_triggerdef(t.oid) FROM pg_trigger t
           JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE NOT t.tgisinternal AND n.nspname='research_station' AND c.relname=%s ORDER BY t.tgname""",
        (table,),
    ).fetchall()
    return [{"name": row[0], "definition": row[1]} for row in rows]


def privileges(conn, table: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """SELECT grantee, privilege_type FROM information_schema.table_privileges
           WHERE table_schema='research_station' AND table_name=%s ORDER BY grantee, privilege_type""",
        (table,),
    ).fetchall()
    return [{"grantee": row[0], "privilege": row[1]} for row in rows]


def classify_columns(
    actual_columns: list[dict[str, Any]], expected_columns: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    actual = {column["column_name"]: column for column in actual_columns}
    missing = sorted(set(expected_columns) - set(actual))
    extra = sorted(set(actual) - set(expected_columns))
    wrong_types: list[str] = []
    wrong_nullability: list[str] = []
    wrong_defaults: list[str] = []
    for name, expected in expected_columns.items():
        observed = actual.get(name)
        if observed is None:
            continue
        if observed["data_type"] != expected["type"]:
            wrong_types.append(name)
        if observed["is_nullable"] != expected["nullable"]:
            wrong_nullability.append(name)
        observed_default = observed["column_default"]
        expected_default = expected["default"]
        if expected_default is None:
            if observed_default is not None:
                wrong_defaults.append(name)
        elif observed_default is None or expected_default not in str(observed_default):
            wrong_defaults.append(name)
    return {
        "missing_columns": missing,
        "wrong_types": sorted(wrong_types),
        "wrong_nullability": sorted(wrong_nullability),
        "wrong_defaults": sorted(wrong_defaults),
        "extra_columns": extra,
    }


def immutable_trigger_locations(conn) -> list[dict[str, str]]:
    rows = conn.execute(
        """SELECT n.nspname, c.relname, pg_get_triggerdef(t.oid)
           FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
           JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE NOT t.tgisinternal AND t.tgname=%s ORDER BY n.nspname, c.relname""",
        (IMMUTABLE_TRIGGER_NAME,),
    ).fetchall()
    return [{"schema": row[0], "table": row[1], "definition": row[2]} for row in rows]


def write_receipt(receipt: dict[str, Any]) -> None:
    REPORT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))


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
        write_receipt(receipt)
        raise SystemExit(2)

    with psycopg.connect(url, options="-c default_transaction_read_only=on") as conn, conn.transaction():
        read_only = conn.execute("SHOW transaction_read_only").fetchone()[0]
        if read_only != "on":
            raise RuntimeError(f"read-only guard failed: {read_only}")
        receipt["postgresql_version"] = conn.execute("SHOW server_version").fetchone()[0]
        receipt["server_version_num"] = conn.execute("SHOW server_version_num").fetchone()[0]
        receipt["current_user"] = conn.execute("SELECT current_user").fetchone()[0]
        receipt["session_user"] = conn.execute("SELECT session_user").fetchone()[0]
        receipt["read_only_guard"] = read_only
        receipt["pgcrypto"] = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname='pgcrypto'"
        ).fetchone()
        receipt["research_station_schema"] = bool(
            conn.execute("SELECT 1 FROM pg_namespace WHERE nspname='research_station'").fetchone()
        )
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
        receipt["immutable_trigger_locations"] = immutable_trigger_locations(conn)
        receipt["reject_function"] = conn.execute(
            "SELECT to_regprocedure('research_station.reject_conversation_message_mutation()')::text"
        ).fetchone()[0]
        receipt["schema_owner"] = conn.execute(
            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='research_station'"
        ).fetchone()
        receipt["relevant_roles"] = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT grantee FROM information_schema.table_privileges WHERE table_schema='research_station' ORDER BY grantee"
            ).fetchall()
        ]
        projects = objects["projects"]
        receipt["migration_101_prerequisite_compatible"] = bool(
            projects["exists"]
            and any(
                column["column_name"] == "project_id"
                and column["data_type"] == "uuid"
                and column["is_nullable"] == "NO"
                for column in projects["columns"]
            )
            and any(
                "PRIMARY KEY (project_id)" in constraint["definition"]
                for constraint in projects["constraints"]
            )
        )
        target_exists = [
            objects[name]["exists"]
            for name in ("conversation_sessions", "conversation_messages")
        ]
        receipt["target_state"] = (
            "ABSENT"
            if target_exists == [False, False]
            else "BOTH_PRESENT"
            if target_exists == [True, True]
            else "PARTIAL"
        )
        receipt["target_contract"] = {
            table: classify_columns(objects[table]["columns"], expected_columns)
            if objects[table]["exists"]
            else {
                "missing_columns": sorted(expected_columns),
                "wrong_types": [],
                "wrong_nullability": [],
                "wrong_defaults": [],
                "extra_columns": [],
            }
            for table, expected_columns in EXPECTED_TARGET_COLUMNS.items()
        }

        unexpected_trigger_locations = [
            trigger
            for trigger in receipt["immutable_trigger_locations"]
            if (trigger["schema"], trigger["table"]) != IMMUTABLE_TRIGGER_RELATION
        ]
        expected_trigger = next(
            (
                trigger
                for trigger in receipt["immutable_trigger_locations"]
                if (trigger["schema"], trigger["table"]) == IMMUTABLE_TRIGGER_RELATION
            ),
            None,
        )
        incompatibilities: list[str] = []
        if not receipt["migration_101_prerequisite_compatible"]:
            incompatibilities.append("MIGRATION_101_PREREQUISITE_INCOMPATIBLE")
        if receipt["target_state"] == "PARTIAL":
            incompatibilities.append("TARGET_TABLES_PARTIAL")
        if receipt["target_state"] == "BOTH_PRESENT":
            malformed_targets = any(
                any(details[key] for key in details)
                for details in receipt["target_contract"].values()
            )
            if malformed_targets:
                incompatibilities.append("TARGET_TABLES_MALFORMED")
            session_constraints = "\n".join(
                item["definition"] for item in objects["conversation_sessions"]["constraints"]
            )
            message_constraints = "\n".join(
                item["definition"] for item in objects["conversation_messages"]["constraints"]
            )
            required_fragments = {
                "SESSION_PRIMARY_KEY_MISSING": (
                    "PRIMARY KEY (conversation_id)", session_constraints
                ),
                "PROJECT_FOREIGN_KEY_MISSING": (
                    "FOREIGN KEY (project_id) REFERENCES research_station.projects(project_id)",
                    session_constraints,
                ),
                "MESSAGE_PRIMARY_KEY_MISSING": (
                    "PRIMARY KEY (message_id)", message_constraints
                ),
                "SESSION_FOREIGN_KEY_MISSING": (
                    "FOREIGN KEY (conversation_id) REFERENCES research_station.conversation_sessions(conversation_id)",
                    message_constraints,
                ),
                "CONVERSATION_CONTEXT_CHECK_MISSING": (
                    "CONVERSATION_CONTEXT", message_constraints
                ),
                "EVIDENCE_AUTHORITY_CHECK_MISSING": (
                    "evidence_authority = false", message_constraints.lower()
                ),
                "PUBLICATION_AUTHORITY_CHECK_MISSING": (
                    "scientific_publication_authorized = false",
                    message_constraints.lower(),
                ),
                "KG_AUTHORITY_CHECK_MISSING": (
                    "knowledge_graph_mutation_authorized = false",
                    message_constraints.lower(),
                ),
            }
            incompatibilities.extend(
                code
                for code, (fragment, text) in required_fragments.items()
                if fragment not in text
            )
            index_names = {
                item["name"]
                for table in ("conversation_sessions", "conversation_messages")
                for item in objects[table]["indexes"]
            }
            if "idx_rs_conversation_owner_project_updated" not in index_names:
                incompatibilities.append("SESSION_INDEX_MISSING")
            if "idx_rs_conversation_messages_session_time" not in index_names:
                incompatibilities.append("MESSAGE_INDEX_MISSING")
            if receipt["reject_function"] is None:
                incompatibilities.append("IMMUTABLE_REJECT_FUNCTION_MISSING")
            if expected_trigger is None:
                incompatibilities.append("IMMUTABLE_TRIGGER_MISSING_ON_TARGET")
            else:
                trigger_definition = expected_trigger["definition"]
                required_trigger_fragments = (
                    "BEFORE DELETE OR UPDATE",
                    "ON research_station.conversation_messages",
                    "EXECUTE FUNCTION research_station.reject_conversation_message_mutation()",
                )
                if not all(
                    fragment in trigger_definition
                    for fragment in required_trigger_fragments
                ):
                    incompatibilities.append("IMMUTABLE_TRIGGER_DEFINITION_INVALID")
            if any(
                privilege["grantee"] == "PUBLIC"
                for table in ("conversation_sessions", "conversation_messages")
                for privilege in objects[table]["privileges"]
            ):
                incompatibilities.append("PUBLIC_PRIVILEGE_PRESENT")
        if unexpected_trigger_locations:
            incompatibilities.append("IMMUTABLE_TRIGGER_NAME_COLLISION")
        receipt["production_mutation_attempted"] = False
        if incompatibilities:
            receipt["status"] = "FAILED_INCOMPATIBLE_PRODUCTION_STATE"
            receipt["incompatibilities"] = sorted(set(incompatibilities))
            receipt["unexpected_trigger_locations"] = unexpected_trigger_locations
        else:
            receipt["status"] = "VERIFIED_READ_ONLY_IN_PRODUCTION"

    write_receipt(receipt)
    if receipt["status"] == "FAILED_INCOMPATIBLE_PRODUCTION_STATE":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
