"""Runs the evidence-feedback suites against both stores.

``file`` is the local/dev store under ``CALYX_EVIDENCE_FEEDBACK_ROOT``;
``postgres`` is the durable store selected whenever a database is configured.
The postgres parameter carries ``requires_postgres`` (tests/conftest.py): it
skips with the driver's reason off-runner and fails in CI when the disposable
database is unusable, so CI cannot turn it green by skipping.

Each postgres test starts from empty ``oc_evidence_feedback`` tables in the
disposable test database. Nothing here is ever pointed at production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.evidence_feedback import routes
from app.evidence_feedback.repository import FileEvidenceFeedbackRepository

STORES = [
    pytest.param("file", id="file"),
    pytest.param("postgres", id="postgres", marks=pytest.mark.requires_postgres),
]


def test_database_url() -> str | None:
    # Same precedence as the requires_postgres probe in tests/conftest.py.
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")


test_database_url.__test__ = False  # a helper, not a test


def truncate_feedback_tables(database_url: str) -> None:
    import psycopg

    from app.evidence_feedback.postgres_repository import (
        SCHEMA,
        TABLES,
        PostgresEvidenceFeedbackRepository,
    )

    PostgresEvidenceFeedbackRepository(database_url)  # ensures the tables exist
    with psycopg.connect(database_url) as conn, conn.cursor() as cur:
        tables = ", ".join(f"{SCHEMA}.{table}" for table in TABLES)
        cur.execute(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")


@dataclass
class FeedbackStore:
    kind: str
    root: Path
    database_url: str | None

    def repository(self):
        """A fresh repository instance: what a restarted process would build."""

        if self.kind == "postgres":
            from app.evidence_feedback.postgres_repository import (
                PostgresEvidenceFeedbackRepository,
            )

            return PostgresEvidenceFeedbackRepository(self.database_url)
        return FileEvidenceFeedbackRepository(self.root)

    def restart(self) -> None:
        """Forget every repository the routes built, as a new process would."""

        routes.reset_repository_cache()

    def files_written(self) -> list[Path]:
        return [path for path in self.root.rglob("*") if path.is_file()]


def make_store(kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FeedbackStore:
    root = tmp_path / "feedback"
    # An explicit root is set for both stores: with a database configured the
    # database must still win, and nothing may be written under the root.
    monkeypatch.setenv(routes.FEEDBACK_ROOT_ENV, str(root))
    routes.reset_repository_cache()
    monkeypatch.setattr(routes, "_POSTGRES_REPOSITORIES", {})
    if kind == "file":
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
        return FeedbackStore(kind, root, None)
    database_url = test_database_url()
    assert database_url, "requires_postgres guarantees a usable test database"
    truncate_feedback_tables(database_url)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("TEST_DATABASE_URL", database_url)
    return FeedbackStore(kind, root, database_url)
