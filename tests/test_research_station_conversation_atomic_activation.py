from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).parents[1]
SCRIPT_PATH = ROOT / "scripts/activate_reasoning_prerequisite_schemas.py"
SPEC = importlib.util.spec_from_file_location("guarded_schema_activation", SCRIPT_PATH)
assert SPEC and SPEC.loader
activation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activation)


def _dsn() -> str:
    return os.environ["TEST_DATABASE_URL"]


def _reset_research_station() -> None:
    with psycopg.connect(_dsn(), autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS research_station CASCADE")


@pytest.fixture(autouse=True)
def clean_research_station():
    _reset_research_station()
    yield
    _reset_research_station()


def test_research_station_migration_identities_are_pinned():
    report = activation.research_station_migration_identity_report()
    assert report["101_research_workspace_foundation.sql"]["actual_git_blob_sha"] == (
        "3333853c97832154cb0f61bace0c2184396da160"
    )
    assert report["140_calyx_conversation_sessions.sql"]["actual_git_blob_sha"] == (
        "f572ba9aa1a3bade4dfe9d1e1faf0dbfb8a57baf"
    )
    assert all(item["matches"] for item in report.values())
    assert all(len(item["sha256"]) == 64 for item in report.values())


def test_clean_database_is_ready_for_atomic_activation():
    with psycopg.connect(_dsn(), autocommit=True) as connection:
        contract = activation.inspect_research_station_conversation_contract(connection)
        assert contract["state"] == "ABSENT"
        result = activation.classify_research_station_preflight(contract, True)
        assert result == {
            "status": "ready",
            "activation_required": True,
            "ready_to_apply": True,
            "blockers": [],
        }


def test_atomic_apply_and_canonical_rerun():
    with psycopg.connect(_dsn(), autocommit=True) as connection:
        result = activation.apply_research_station_conversation_chain(connection)
        assert result["applied_migrations"] == [
            "101_research_workspace_foundation.sql",
            "140_calyx_conversation_sessions.sql",
        ]
        assert result["contract_after"]["complete"] is True
        assert result["contract_after"]["blockers"] == []

        rerun = activation.apply_research_station_conversation_chain(connection)
        assert rerun["applied_migrations"] == []
        assert rerun["already_complete"] is True
        assert rerun["contract_after"]["complete"] is True


def test_failure_after_101_rolls_back_entire_chain():
    with psycopg.connect(_dsn(), autocommit=True) as connection:
        with pytest.raises(RuntimeError, match="INTENTIONAL_FAILURE_AFTER_101"):
            activation.apply_research_station_conversation_chain(
                connection, inject_failure_after="101"
            )
        contract = activation.inspect_research_station_conversation_contract(connection)
        assert contract["state"] == "ABSENT"
        assert connection.execute(
            "SELECT to_regclass('research_station.projects'), "
            "to_regclass('research_station.conversation_sessions')"
        ).fetchone() == (None, None)


def test_failure_after_140_rolls_back_101_and_140():
    with psycopg.connect(_dsn(), autocommit=True) as connection:
        with pytest.raises(RuntimeError, match="INTENTIONAL_FAILURE_AFTER_140"):
            activation.apply_research_station_conversation_chain(
                connection, inject_failure_after="140"
            )
        contract = activation.inspect_research_station_conversation_contract(connection)
        assert contract["state"] == "ABSENT"
        assert connection.execute(
            "SELECT to_regclass('research_station.projects'), "
            "to_regclass('research_station.conversation_sessions'), "
            "to_regclass('research_station.conversation_messages')"
        ).fetchone() == (None, None, None)


def test_malformed_existing_101_fails_closed_without_repair():
    with psycopg.connect(_dsn(), autocommit=True) as connection:
        connection.execute("CREATE SCHEMA research_station")
        connection.execute(
            "CREATE TABLE research_station.projects (project_id uuid PRIMARY KEY)"
        )
        contract = activation.inspect_research_station_conversation_contract(connection)
        assert contract["safe_resume"] is False
        assert "MALFORMED_OR_PARTIAL_MIGRATION_101_STATE" in contract["blockers"]
        result = activation.classify_research_station_preflight(contract, True)
        assert result["status"] == "blocked"
        with pytest.raises(RuntimeError, match="RESEARCH_STATION_PREFLIGHT_BLOCKED"):
            activation.apply_research_station_conversation_chain(connection)
        assert connection.execute(
            "SELECT to_regclass('research_station.conversation_sessions')"
        ).fetchone()[0] is None


def test_governance_foreign_key_and_append_only_behavior():
    with psycopg.connect(_dsn(), autocommit=True) as connection:
        activation.apply_research_station_conversation_chain(connection)
        with connection.transaction():
            project_id = connection.execute(
                "INSERT INTO research_station.projects(owner_subject,title) "
                "VALUES ('owner-a','fixture') RETURNING project_id"
            ).fetchone()[0]
            conversation_id = connection.execute(
                "INSERT INTO research_station.conversation_sessions(owner_subject,project_id) "
                "VALUES ('owner-a',%s) RETURNING conversation_id",
                (project_id,),
            ).fetchone()[0]
            message_id = connection.execute(
                "INSERT INTO research_station.conversation_messages"
                "(conversation_id,owner_subject,role,content) "
                "VALUES (%s,'owner-a','OPERATOR','fixture') RETURNING message_id",
                (conversation_id,),
            ).fetchone()[0]

        for statement, params, expected_state in (
            (
                "INSERT INTO research_station.conversation_sessions(owner_subject,project_id) "
                "VALUES ('owner-a','00000000-0000-0000-0000-000000000001')",
                (),
                "23503",
            ),
            (
                "INSERT INTO research_station.conversation_messages"
                "(conversation_id,owner_subject,role,content,data_status) "
                "VALUES (%s,'owner-a','OPERATOR','x','EVIDENCE')",
                (conversation_id,),
                "23514",
            ),
            (
                "INSERT INTO research_station.conversation_messages"
                "(conversation_id,owner_subject,role,content,evidence_authority) "
                "VALUES (%s,'owner-a','OPERATOR','x',true)",
                (conversation_id,),
                "23514",
            ),
            (
                "INSERT INTO research_station.conversation_messages"
                "(conversation_id,owner_subject,role,content,scientific_publication_authorized) "
                "VALUES (%s,'owner-a','OPERATOR','x',true)",
                (conversation_id,),
                "23514",
            ),
            (
                "INSERT INTO research_station.conversation_messages"
                "(conversation_id,owner_subject,role,content,knowledge_graph_mutation_authorized) "
                "VALUES (%s,'owner-a','OPERATOR','x',true)",
                (conversation_id,),
                "23514",
            ),
            (
                "UPDATE research_station.conversation_messages SET content='changed' "
                "WHERE message_id=%s",
                (message_id,),
                "P0001",
            ),
            (
                "DELETE FROM research_station.conversation_messages WHERE message_id=%s",
                (message_id,),
                "P0001",
            ),
        ):
            with pytest.raises(psycopg.Error) as exc_info, connection.transaction():
                connection.execute(statement, params)
            assert exc_info.value.sqlstate == expected_state

        assert connection.execute(
            "SELECT content FROM research_station.conversation_messages WHERE message_id=%s",
            (message_id,),
        ).fetchone()[0] == "fixture"


def test_transaction_lock_contends_with_existing_session_lock_namespace():
    with (
        psycopg.connect(_dsn(), autocommit=True) as holder,
        psycopg.connect(_dsn(), autocommit=True) as contender,
    ):
        holder.execute(
            "SELECT pg_advisory_lock(%s)", (activation.POSTGRES_VALIDATION_LOCK_ID,)
        )
        try:
            with pytest.raises(psycopg.errors.LockNotAvailable), contender.transaction():
                contender.execute("SET LOCAL lock_timeout='200ms'")
                contender.execute(
                    "SELECT pg_advisory_xact_lock(%s)",
                    (activation.POSTGRES_VALIDATION_LOCK_ID,),
                )
        finally:
            holder.execute(
                "SELECT pg_advisory_unlock(%s)",
                (activation.POSTGRES_VALIDATION_LOCK_ID,),
            )
