from __future__ import annotations

import os
from pathlib import Path

import pytest


DATABASE_URL = os.getenv("BUILD_090B_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="BUILD_090B_DATABASE_URL unavailable"
)


def test_additive_migration_and_append_only_postgresql_contract():
    import psycopg

    migration = Path(
        "migrations/090b_design_reasoning_interface_planning_foundation.sql"
    ).read_text()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(migration)
        cur.execute(migration)
        cur.execute(
            "INSERT INTO design_planning.product_requests "
            "(artifact_id, logical_key, version, integrity_hash, payload) "
            "VALUES ('test-request','test-logical',1,%s,'{}') ON CONFLICT DO NOTHING",
            ("a" * 64,),
        )
        with pytest.raises(psycopg.Error, match="immutable"):
            cur.execute(
                "UPDATE design_planning.product_requests SET payload='{}' "
                "WHERE artifact_id='test-request'"
            )
        with pytest.raises(psycopg.Error, match="future implementation state"):
            cur.execute(
                "INSERT INTO design_planning.interface_plans "
                "(artifact_id,logical_key,version,integrity_hash,lifecycle_state,payload) "
                "VALUES ('future-plan','future',1,%s,'IMPLEMENTED','{}')",
                ("b" * 64,),
            )


def test_postgresql_constraints_cover_every_append_only_artifact():
    import psycopg

    expected = {
        "product_requests",
        "project_context_snapshots",
        "design_evidence_packages",
        "design_reasoning_records",
        "material_conflict_records",
        "interface_plans",
        "review_records",
        "audit_events",
    }
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT event_object_table FROM information_schema.triggers "
            "WHERE trigger_schema='design_planning' AND trigger_name='immutable_090b'"
        )
        assert {row[0] for row in cur.fetchall()} == expected
