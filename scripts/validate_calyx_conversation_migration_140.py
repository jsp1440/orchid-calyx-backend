from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import psycopg

ROOT = Path(__file__).resolve().parents[1]
M101 = ROOT / "migrations/101_research_workspace_foundation.sql"
M140 = ROOT / "migrations/140_calyx_conversation_sessions.sql"
EXPECTED_M140_BLOB = "f572ba9aa1a3bade4dfe9d1e1faf0dbfb8a57baf"
REPORT = Path(os.environ.get("M140_REPORT", "migration-140-disposable-report.json"))

EXPECTED_COLUMNS = {
    "conversation_sessions": {
        "conversation_id": "uuid", "owner_subject": "text", "project_id": "uuid",
        "title": "text", "active_taxon_id": "text", "active_document_id": "text",
        "created_at": "timestamp with time zone", "updated_at": "timestamp with time zone",
        "archived_at": "timestamp with time zone", "version": "integer",
    },
    "conversation_messages": {
        "message_id": "uuid", "conversation_id": "uuid", "owner_subject": "text",
        "role": "text", "content": "text", "epistemic_status": "text",
        "context_json": "jsonb", "source_refs_json": "jsonb", "tool_trace_json": "jsonb",
        "data_status": "text", "evidence_authority": "boolean",
        "scientific_publication_authorized": "boolean",
        "knowledge_graph_mutation_authorized": "boolean",
        "created_at": "timestamp with time zone",
    },
}


def blob_sha(path: Path) -> str:
    return subprocess.check_output(["git", "hash-object", str(path)], text=True).strip()


def table_exists(conn, table: str) -> bool:
    return bool(conn.execute("SELECT to_regclass(%s)", (f"research_station.{table}",)).fetchone()[0])


def columns(conn, table: str) -> dict[str, str]:
    rows = conn.execute(
        """SELECT column_name, data_type FROM information_schema.columns
           WHERE table_schema='research_station' AND table_name=%s""", (table,)
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def constraints(conn, table: str) -> list[str]:
    rows = conn.execute(
        """SELECT pg_get_constraintdef(c.oid)
           FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid
           JOIN pg_namespace n ON n.oid=t.relnamespace
           WHERE n.nspname='research_station' AND t.relname=%s""", (table,)
    ).fetchall()
    return [r[0] for r in rows]


def indexes(conn, table: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname='research_station' AND tablename=%s", (table,)
    ).fetchall()]


def trigger_defs(conn, table: str) -> list[str]:
    return [r[0] for r in conn.execute(
        """SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t
           JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE NOT t.tgisinternal AND n.nspname='research_station' AND c.relname=%s""", (table,)
    ).fetchall()]


def inspect_contract(conn) -> dict[str, Any]:
    state: dict[str, Any] = {"tables": {}}
    malformed = False
    for table, expected in EXPECTED_COLUMNS.items():
        exists = table_exists(conn, table)
        actual = columns(conn, table) if exists else {}
        missing = sorted(set(expected) - set(actual))
        wrong = sorted(k for k, v in expected.items() if k in actual and actual[k] != v)
        state["tables"][table] = {"exists": exists, "missing_columns": missing, "wrong_types": wrong}
        malformed |= exists and bool(missing or wrong)
    one_exists = sum(int(v["exists"]) for v in state["tables"].values()) == 1
    malformed |= one_exists
    state["classification"] = "MALFORMED_PARTIAL" if malformed else (
        "CANONICAL_OR_COMPLETE" if all(v["exists"] for v in state["tables"].values()) else "ABSENT"
    )
    return state


def assert_prerequisite(conn) -> None:
    assert table_exists(conn, "projects")
    c = columns(conn, "projects")
    assert c.get("project_id") == "uuid"
    assert any("PRIMARY KEY (project_id)" in x for x in constraints(conn, "projects"))


def assert_contract(conn) -> dict[str, Any]:
    report = inspect_contract(conn)
    assert report["classification"] == "CANONICAL_OR_COMPLETE", report
    for table, expected in EXPECTED_COLUMNS.items():
        actual = columns(conn, table)
        assert actual == expected, (table, actual)
    s_cons = constraints(conn, "conversation_sessions")
    m_cons = constraints(conn, "conversation_messages")
    assert any("PRIMARY KEY (conversation_id)" in x for x in s_cons)
    assert any("FOREIGN KEY (project_id) REFERENCES research_station.projects(project_id)" in x for x in s_cons)
    assert any("PRIMARY KEY (message_id)" in x for x in m_cons)
    assert any("FOREIGN KEY (conversation_id) REFERENCES research_station.conversation_sessions(conversation_id)" in x for x in m_cons)
    joined = "\n".join(m_cons)
    for token in ("CONVERSATION_CONTEXT", "evidence_authority = false", "scientific_publication_authorized = false", "knowledge_graph_mutation_authorized = false"):
        assert token.lower() in joined.lower(), token
    assert "idx_rs_conversation_owner_project_updated" in indexes(conn, "conversation_sessions")
    assert "idx_rs_conversation_messages_session_time" in indexes(conn, "conversation_messages")
    triggers = "\n".join(trigger_defs(conn, "conversation_messages"))
    assert "rs_conversation_messages_immutable" in triggers
    assert conn.execute("SELECT to_regprocedure('research_station.reject_conversation_message_mutation()')").fetchone()[0]
    public = conn.execute(
        """SELECT table_name, privilege_type FROM information_schema.table_privileges
           WHERE table_schema='research_station' AND table_name IN ('conversation_sessions','conversation_messages')
           AND grantee='PUBLIC'"""
    ).fetchall()
    assert public == [], public
    return {"constraints": {"sessions": s_cons, "messages": m_cons}, "triggers": triggers}


def expect_failure(conn, sql: str, params: tuple[Any, ...] = ()) -> str:
    try:
        with conn.transaction():
            conn.execute(sql, params)
    except psycopg.Error as exc:
        return exc.sqlstate or type(exc).__name__
    raise AssertionError(f"statement unexpectedly succeeded: {sql}")


def cleanup_targets(conn) -> None:
    with conn.transaction():
        conn.execute("DROP TABLE IF EXISTS research_station.conversation_messages CASCADE")
        conn.execute("DROP TABLE IF EXISTS research_station.conversation_sessions CASCADE")
        conn.execute("DROP FUNCTION IF EXISTS research_station.reject_conversation_message_mutation() CASCADE")


def main() -> None:
    url = os.environ["DATABASE_URL"]
    identity = {
        "git_blob_sha": blob_sha(M140),
        "expected_git_blob_sha": EXPECTED_M140_BLOB,
        "sha256": hashlib.sha256(M140.read_bytes()).hexdigest(),
    }
    assert identity["git_blob_sha"] == EXPECTED_M140_BLOB, identity
    receipt: dict[str, Any] = {"migration_identity": identity, "stages": {}}
    with psycopg.connect(url) as conn:
        receipt["postgresql_version"] = conn.execute("SHOW server_version").fetchone()[0]
        with conn.transaction():
            conn.execute(M101.read_text())
        assert_prerequisite(conn)
        receipt["stages"]["prerequisite_101"] = "PASS"

        cleanup_targets(conn)
        assert inspect_contract(conn)["classification"] == "ABSENT"
        with conn.transaction():
            conn.execute(M140.read_text())
            assert_contract(conn)
        receipt["stages"]["apply_transactional"] = "PASS"

        with conn.transaction():
            project_id = conn.execute("INSERT INTO research_station.projects(owner_subject,title) VALUES ('owner-a','fixture') RETURNING project_id").fetchone()[0]
            session_id = conn.execute("INSERT INTO research_station.conversation_sessions(owner_subject,project_id) VALUES ('owner-a',%s) RETURNING conversation_id", (project_id,)).fetchone()[0]
            message_id = conn.execute("INSERT INTO research_station.conversation_messages(conversation_id,owner_subject,role,content) VALUES (%s,'owner-a','OPERATOR','fixture') RETURNING message_id", (session_id,)).fetchone()[0]
        receipt["stages"]["valid_insert"] = "PASS"
        receipt["failure_sqlstates"] = {
            "bad_project_fk": expect_failure(conn, "INSERT INTO research_station.conversation_sessions(owner_subject,project_id) VALUES ('owner-a','00000000-0000-0000-0000-000000000001')"),
            "bad_context": expect_failure(conn, "INSERT INTO research_station.conversation_messages(conversation_id,owner_subject,role,content,data_status) VALUES (%s,'owner-a','OPERATOR','x','EVIDENCE')", (session_id,)),
            "evidence_true": expect_failure(conn, "INSERT INTO research_station.conversation_messages(conversation_id,owner_subject,role,content,evidence_authority) VALUES (%s,'owner-a','OPERATOR','x',true)", (session_id,)),
            "publication_true": expect_failure(conn, "INSERT INTO research_station.conversation_messages(conversation_id,owner_subject,role,content,scientific_publication_authorized) VALUES (%s,'owner-a','OPERATOR','x',true)", (session_id,)),
            "kg_true": expect_failure(conn, "INSERT INTO research_station.conversation_messages(conversation_id,owner_subject,role,content,knowledge_graph_mutation_authorized) VALUES (%s,'owner-a','OPERATOR','x',true)", (session_id,)),
            "update_message": expect_failure(conn, "UPDATE research_station.conversation_messages SET content='changed' WHERE message_id=%s", (message_id,)),
            "delete_message": expect_failure(conn, "DELETE FROM research_station.conversation_messages WHERE message_id=%s", (message_id,)),
        }
        assert all(receipt["failure_sqlstates"].values())
        assert conn.execute("SELECT content FROM research_station.conversation_messages WHERE message_id=%s", (message_id,)).fetchone()[0] == "fixture"
        receipt["stages"]["governance_and_append_only"] = "PASS"

        with conn.transaction():
            conn.execute("CREATE ROLE calyx_app_validation NOLOGIN")
            conn.execute("GRANT USAGE ON SCHEMA research_station TO calyx_app_validation")
            conn.execute("GRANT SELECT,INSERT,UPDATE ON research_station.conversation_sessions TO calyx_app_validation")
            conn.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON research_station.conversation_messages TO calyx_app_validation")
            conn.execute("SET LOCAL ROLE calyx_app_validation")
            conn.execute("SELECT count(*) FROM research_station.conversation_sessions")
            conn.execute("INSERT INTO research_station.conversation_sessions(owner_subject) VALUES ('role-test')")
        with conn.transaction():
            conn.execute("DROP ROLE calyx_app_validation")
        receipt["stages"]["explicit_application_role_simulation"] = "PASS"

        with conn.transaction():
            conn.execute(M140.read_text())
            assert_contract(conn)
        receipt["stages"]["reapply_idempotency"] = "PASS"

        cleanup_targets(conn)
        with conn.transaction():
            conn.execute("CREATE TABLE research_station.conversation_sessions (conversation_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_subject text NOT NULL, project_id uuid, updated_at timestamptz NOT NULL DEFAULT now())")
            conn.execute("CREATE TABLE research_station.conversation_messages (message_id uuid PRIMARY KEY DEFAULT gen_random_uuid(), conversation_id uuid NOT NULL, owner_subject text NOT NULL, role text NOT NULL, content text NOT NULL, created_at timestamptz NOT NULL DEFAULT now())")
        malformed = inspect_contract(conn)
        assert malformed["classification"] == "MALFORMED_PARTIAL", malformed
        receipt["stages"]["malformed_existing_state_detection"] = "PASS"
        cleanup_targets(conn)

        try:
            with conn.transaction():
                conn.execute(M140.read_text())
                assert_contract(conn)
                raise RuntimeError("intentional rollback probe")
        except RuntimeError:
            pass
        assert inspect_contract(conn)["classification"] == "ABSENT"
        receipt["stages"]["transaction_rollback"] = "PASS"

        with conn.transaction():
            conn.execute(M140.read_text())
            receipt["final_contract"] = assert_contract(conn)
        receipt["stages"]["final_canonical_state"] = "PASS"

    receipt["status"] = "VERIFIED_IN_DISPOSABLE_POSTGRESQL"
    REPORT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
