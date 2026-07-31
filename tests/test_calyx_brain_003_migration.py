import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]


def test_migration_is_additive_and_scoped():
    sql = (ROOT / "migrations/105_reasoning_ledger_publication_adapter.sql").read_text()
    lowered = sql.lower()
    assert "create schema if not exists reasoning_publication" in lowered
    assert lowered.count("create table if not exists reasoning_publication.") == 2
    assert "references reasoning_ledger.ledger_heads" in lowered
    assert "references oc_knowledge_publication.publication_candidates" in lowered
    assert "drop table" not in lowered
    assert "truncate" not in lowered
    assert "oc_graph.kg_" not in lowered


def test_rollback_only_removes_adapter_schema():
    sql = (
        (ROOT / "migrations/105_reasoning_ledger_publication_adapter_rollback.sql")
        .read_text()
        .lower()
    )
    assert "drop schema if exists reasoning_publication cascade" in sql
    assert "reasoning_ledger" not in sql
    assert "oc_knowledge_publication" not in sql
    assert "oc_graph" not in sql


def test_route_is_registered_without_direct_graph_sql():
    main = (ROOT / "app/main.py").read_text()
    routes = (ROOT / "app/reasoning_publication/routes.py").read_text()
    service = (ROOT / "app/reasoning_publication/service.py").read_text()
    gateway = (ROOT / "app/reasoning_publication/gateway.py").read_text()
    assert "app.include_router(reasoning_publication_router)" in main
    assert '@router.post("/{ledger_id}/publish")' in routes
    assert "INSERT INTO oc_graph" not in service
    assert "INSERT INTO oc_graph" not in routes
    assert "ControlledGraphPublicationService" in gateway


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured"
)
def test_postgres_dependency_order_reapplication_and_rollback_isolation():
    import psycopg

    dsn = os.environ["TEST_DATABASE_URL"]
    chain = (
        "087b_context_preserving_interpretation.sql",
        "088b_publication_registry_policy_foundation.sql",
        "088c_atomic_graph_transaction_publication_engine.sql",
        "088d_publication_lifecycle_corrections_rollback.sql",
        "101_research_workspace_foundation.sql",
        "103_reasoning_ledger.sql",
        "104_orchid_continuum_brain.sql",
        "105_reasoning_ledger_publication_adapter.sql",
    )
    with psycopg.connect(dsn, autocommit=True) as connection:
        for migration in chain:
            connection.execute((ROOT / "migrations" / migration).read_text())
        connection.execute(
            (
                ROOT / "migrations/105_reasoning_ledger_publication_adapter.sql"
            ).read_text()
        )
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname='reasoning_publication'"
            )
        }
        assert tables == {"publication_artifacts", "publication_attempts"}
        connection.execute(
            (
                ROOT
                / "migrations/105_reasoning_ledger_publication_adapter_rollback.sql"
            ).read_text()
        )
        assert connection.execute(
            "SELECT to_regclass('reasoning_ledger.ledger_heads'),"
            "to_regclass('oc_knowledge_publication.publication_candidates'),"
            "to_regclass('oc_brain.connector_registrations')"
        ).fetchone() == (
            "reasoning_ledger.ledger_heads",
            "oc_knowledge_publication.publication_candidates",
            "oc_brain.connector_registrations",
        )
