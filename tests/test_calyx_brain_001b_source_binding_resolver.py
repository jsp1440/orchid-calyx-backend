from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from app.literature_extraction.source_binding import LiteratureSourceBindingError
from app.literature_extraction.source_binding_postgres import (
    PostgresLiteratureSourceBindingResolver,
)


SOURCE_HASH = "a" * 64


def _paper(*, start: int = 10, end: int = 20):
    evidence = SimpleNamespace(
        evidence_id="evidence-1",
        span=SimpleNamespace(char_start=start, char_end=end),
    )
    return SimpleNamespace(
        paper_id="paper-1",
        source=SimpleNamespace(content_hash=SOURCE_HASH),
        analysis_manifest=SimpleNamespace(analysis_id="analysis-1"),
        evidence=[evidence],
    )


def _dsn() -> str | None:
    return os.getenv("CALYX_BRAIN_001B_TEST_DATABASE_URL")


def _bootstrap(dsn: str) -> None:
    migration = Path("migrations/171_literature_source_binding_resolver.sql").read_text(
        encoding="utf-8"
    )
    with psycopg.connect(dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA IF EXISTS oc_document_intelligence CASCADE")
            cursor.execute("DROP SCHEMA IF EXISTS oc_import CASCADE")
            cursor.execute("CREATE SCHEMA oc_import")
            cursor.execute(
                "CREATE TABLE oc_import.document_revisions (revision_id BIGINT PRIMARY KEY)"
            )
            cursor.execute("CREATE SCHEMA oc_document_intelligence")
            cursor.execute(
                """
                CREATE TABLE oc_document_intelligence.records (
                    record_id BIGINT PRIMARY KEY,
                    revision_id BIGINT NOT NULL REFERENCES oc_import.document_revisions(revision_id),
                    source_sha256 CHAR(64) NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE oc_document_intelligence.extraction_runs (
                    extraction_run_id BIGINT PRIMARY KEY,
                    record_id BIGINT NOT NULL REFERENCES oc_document_intelligence.records(record_id),
                    state TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE oc_document_intelligence.source_anchors (
                    anchor_id BIGINT PRIMARY KEY,
                    revision_id BIGINT NOT NULL REFERENCES oc_import.document_revisions(revision_id),
                    extraction_run_id BIGINT NOT NULL REFERENCES oc_document_intelligence.extraction_runs(extraction_run_id),
                    char_start BIGINT,
                    char_end BIGINT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE oc_document_intelligence.display_policies (
                    record_id BIGINT PRIMARY KEY REFERENCES oc_document_intelligence.records(record_id),
                    display_state TEXT NOT NULL,
                    internal_use_permission BOOLEAN NOT NULL
                )
                """
            )
            cursor.execute(migration)
            cursor.execute("INSERT INTO oc_import.document_revisions VALUES (11)")
            cursor.execute(
                "INSERT INTO oc_document_intelligence.records VALUES (21, 11, %s)",
                (SOURCE_HASH,),
            )
            cursor.execute(
                "INSERT INTO oc_document_intelligence.extraction_runs VALUES (31, 21, 'COMPLETED')"
            )
            cursor.execute(
                "INSERT INTO oc_document_intelligence.source_anchors VALUES (41, 11, 31, 10, 20)"
            )
            cursor.execute(
                "INSERT INTO oc_document_intelligence.display_policies VALUES (21, 'INTERNAL_RESEARCH_ONLY', TRUE)"
            )


@pytest.mark.skipif(_dsn() is None, reason="PostgreSQL validation DSN not configured")
def test_transactional_resolver_is_idempotent_and_exact():
    dsn = _dsn()
    assert dsn is not None
    _bootstrap(dsn)
    resolver = PostgresLiteratureSourceBindingResolver(lambda: psycopg.connect(dsn))

    first = resolver.resolve(_paper(), actor="pytest", tenant_id="t1", project_id="p1")
    second = resolver.resolve(_paper(), actor="pytest", tenant_id="t1", project_id="p1")

    assert first.created is True
    assert second.created is False
    assert first.binding_id == second.binding_id
    assert first.binding.source_object_id == 21
    assert first.binding.revision_id == 11
    assert first.binding.extraction_run_id == 31
    assert first.binding.anchor_ids == {"evidence-1": 41}


@pytest.mark.skipif(_dsn() is None, reason="PostgreSQL validation DSN not configured")
def test_transactional_resolver_rejects_unmatched_anchor():
    dsn = _dsn()
    assert dsn is not None
    _bootstrap(dsn)
    resolver = PostgresLiteratureSourceBindingResolver(lambda: psycopg.connect(dsn))

    with pytest.raises(LiteratureSourceBindingError) as captured:
        resolver.resolve(_paper(start=12, end=22), actor="pytest")

    assert captured.value.code == "ANCHOR_BINDING_NOT_FOUND"


@pytest.mark.skipif(_dsn() is None, reason="PostgreSQL validation DSN not configured")
def test_transactional_resolver_fails_closed_on_multiple_runs():
    dsn = _dsn()
    assert dsn is not None
    _bootstrap(dsn)
    with psycopg.connect(dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO oc_document_intelligence.extraction_runs VALUES (32, 21, 'READY_FOR_REVIEW')"
            )
    resolver = PostgresLiteratureSourceBindingResolver(lambda: psycopg.connect(dsn))

    with pytest.raises(LiteratureSourceBindingError) as captured:
        resolver.resolve(_paper(), actor="pytest")

    assert captured.value.code == "BINDING_CONFLICT_REQUIRES_REVIEW"


def test_migration_is_additive_and_references_canonical_anchors():
    sql = Path("migrations/171_literature_source_binding_resolver.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE IF NOT EXISTS" in sql
    assert "REFERENCES oc_document_intelligence.source_anchors(anchor_id)" in sql
    assert "REFERENCES oc_document_intelligence.extraction_runs(extraction_run_id)" in sql
    assert "DROP TABLE" not in sql.upper()
    assert "TRUNCATE" not in sql.upper()
