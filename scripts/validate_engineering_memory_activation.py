"""Prove Engineering Memory activation readiness on an ephemeral PostgreSQL DB.

This command is deliberately fail-closed. It cannot run unless the caller sets
the explicit ephemeral-validation sentinel and targets a loopback PostgreSQL
database whose name starts with ``engineering_memory_ephemeral_``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.engineering_memory.models import EVIDENCE_CLASS_NON_SCIENTIFIC
from app.engineering_memory.service import EngineeringMemoryService

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "engineering_memory_runs",
    "engineering_memory_lessons",
    "engineering_memory_retrievals",
}


class UnsafeValidationTarget(ValueError):
    """The requested database is not demonstrably ephemeral and local."""


def validated_ephemeral_url(environ: dict[str, str]) -> str:
    if environ.get("ENGINEERING_MEMORY_EPHEMERAL_VALIDATION") != "1":
        raise UnsafeValidationTarget("ephemeral-validation sentinel is required")
    raw = environ.get("ENGINEERING_MEMORY_TEST_DATABASE_URL", "")
    parsed = urlparse(raw.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise UnsafeValidationTarget("a PostgreSQL test URL is required")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise UnsafeValidationTarget("only a loopback PostgreSQL host is allowed")
    database = parsed.path.lstrip("/")
    if not database.startswith("engineering_memory_ephemeral_"):
        raise UnsafeValidationTarget("database name must carry the ephemeral prefix")
    return raw


def _execute_sql(engine, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    with engine.begin() as connection:
        connection.exec_driver_sql(sql)


def _memory_tables(engine) -> set[str]:
    return EXPECTED_TABLES.intersection(inspect(engine).get_table_names())


def run_validation(database_url: str) -> dict:
    engine = create_engine(database_url, pool_pre_ping=True)
    upgrade = ROOT / "migrations/082_engineering_memory.sql"
    downgrade = ROOT / "migrations/082_engineering_memory_downgrade.sql"
    checks: dict[str, bool] = {}
    try:
        _execute_sql(engine, downgrade)
        _execute_sql(engine, upgrade)
        _execute_sql(engine, upgrade)
        checks["migration_idempotent"] = _memory_tables(engine) == EXPECTED_TABLES

        session = sessionmaker(bind=engine)()
        service = EngineeringMemoryService()
        try:
            scope = "ephemeral/readiness-a"
            other_scope = "ephemeral/readiness-b"
            fake_secret = "ghp_abcdefghijklmnopqrstuvwx1234"
            run = service.capture_run(
                session,
                {
                    "executor": "readiness-validator",
                    "workspace_scope": scope,
                    "repository": "synthetic/engineering-memory",
                    "outcome": "success",
                    "data_classification": "internal_engineering",
                    "sanitized_summary": (
                        f"synthetic token {fake_secret}; synthetic locality "
                        "-0.1807, -78.4678"
                    ),
                    "tokens_input": 0,
                },
            )
            checks["secret_redaction"] = fake_secret not in run.sanitized_summary
            checks["locality_redaction"] = "-0.1807" not in run.sanitized_summary
            lesson = service.create_lesson(
                session,
                {
                    "workspace_scope": scope,
                    "repository": "synthetic/engineering-memory",
                    "module": "app/engineering_memory",
                    "problem": "rollback ordering failed",
                    "cause": "foreign-key dependency",
                    "solution": "drop retrievals before lessons and runs",
                    "applicability": "schema rollback",
                    "source_run_id": run.run_id,
                    "data_classification": "internal_engineering",
                },
            )
            service.verify_lesson(
                session, lesson.lesson_id, scope, {"check": "synthetic-pass"}
            )
            own = service.retrieve(
                session,
                {
                    "workspace_scope": scope,
                    "repository": "synthetic/engineering-memory",
                    "query": "foreign key rollback ordering",
                    "injected": True,
                },
            )
            other = service.retrieve(
                session,
                {
                    "workspace_scope": other_scope,
                    "repository": "synthetic/engineering-memory",
                    "query": "foreign key rollback ordering",
                },
            )
            checks["retrieval"] = [s.lesson.lesson_id for s in own.scored] == [
                lesson.lesson_id
            ]
            checks["scope_isolation"] = other.scored == []
            service.record_feedback(
                session,
                own.retrieval.retrieval_id,
                scope,
                {"feedback": "helpful", "estimated_tokens_saved": 0},
            )
            metrics = service.metrics(session, scope)
            checks["zero_vs_unavailable"] = (
                metrics["runs"]["tokens_input"] == 0
                and metrics["runs"]["tokens_output"] is None
            )
            service.invalidate_lesson(session, lesson.lesson_id, scope, "synthetic")
            after = service.retrieve(
                session,
                {
                    "workspace_scope": scope,
                    "repository": "synthetic/engineering-memory",
                    "query": "foreign key rollback ordering",
                },
            )
            checks["invalidation_exclusion"] = after.scored == []
            checks["non_scientific_boundary"] = (
                lesson.evidence_class == EVIDENCE_CLASS_NON_SCIENTIFIC
            )
            session.commit()
        finally:
            session.close()

        _execute_sql(engine, downgrade)
        checks["rollback"] = _memory_tables(engine) == set()
        _execute_sql(engine, upgrade)
        checks["reupgrade"] = _memory_tables(engine) == EXPECTED_TABLES
    finally:
        try:
            _execute_sql(engine, downgrade)
        finally:
            engine.dispose()

    return {
        "status": "ready" if all(checks.values()) else "not_ready",
        "checks": checks,
        "production_activation": "blocked_pending_owner_checkpoint",
        "scientific_state_changed": False,
    }


def main() -> int:
    try:
        url = validated_ephemeral_url(dict(os.environ))
        report = run_validation(url)
    except Exception as exc:  # noqa: BLE001 - emit a sanitized fail-closed report
        report = {
            "status": "not_ready",
            "error": type(exc).__name__,
            "production_activation": "blocked_pending_owner_checkpoint",
            "scientific_state_changed": False,
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
