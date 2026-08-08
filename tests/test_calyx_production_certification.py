from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from runtime import calyx_core_certification as certification


def test_default_builder_preserves_non_live_contract(tmp_path: Path) -> None:
    report = certification.build_calyx_core_certification(
        taxonomy_root=tmp_path / "taxonomy",
        literature_root=tmp_path / "literature",
        env={},
    )
    assert report["contract"] == "calyx-core-certification-v2"
    assert report["no_production_mutation"] is True
    assert "production_observability" not in report


def test_live_certification_reports_commit_drift_without_secret_values(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr("app.database.get_engine", lambda: engine)
    env = {
        "CALYX_DEPLOYED_COMMIT": "deployed-123",
        "CALYX_EXPECTED_MAIN_COMMIT": "main-456",
        "DATABASE_URL": "postgresql://secret-user:secret-pass@example.invalid/db",
        "CALYX_API_KEY": "super-secret-api-key",
        "CALYX_OWNER_ACCESS_CODE": "super-secret-owner-code",
        "CALYX_OWNER_SESSION_SECRET": "super-secret-session",
    }

    report = certification._production_observability(env)

    assert report["contract"] == "calyx-production-certification-v1"
    assert report["read_only"] is True
    assert report["secret_values_returned"] is False
    assert report["deployment"] == {
        "deployed_commit": "deployed-123",
        "expected_main_commit": "main-456",
        "matches_expected_main": False,
    }
    assert report["database"]["reachable"] is True
    assert report["database"]["dialect"] == "sqlite"
    assert report["authentication_configuration"] == {
        "database_url": "present",
        "api_key": "present",
        "owner_access_code": "present",
        "owner_session_secret": "present",
    }
    assert "DEPLOYED_COMMIT_BEHIND_MAIN" in report["blockers"]
    rendered = repr(report)
    assert "secret-pass" not in rendered
    assert "super-secret-api-key" not in rendered
    assert "super-secret-owner-code" not in rendered
    assert "super-secret-session" not in rendered
    assert report["production_database_mutation"] is False
    assert report["production_knowledge_graph_mutation"] is False


def test_live_certification_marks_missing_config_and_unknown_graph_version(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr("app.database.get_engine", lambda: engine)

    report = certification._production_observability({})

    assert report["database"]["reachable"] is True
    assert report["deployment"]["matches_expected_main"] is None
    assert "DEPLOYED_COMMIT_UNAVAILABLE" in report["blockers"]
    assert "EXPECTED_MAIN_COMMIT_UNAVAILABLE" in report["blockers"]
    assert "GRAPH_VERSION_UNAVAILABLE" in report["blockers"]
    assert "CONFIGURATION_ABSENT:database_url" in report["blockers"]
    assert report["queues"]["engineering_job_status_counts"] is None


@pytest.mark.skipif(
    not os.getenv("CALYX_CERTIFICATION_TEST_DATABASE_URL"),
    reason="CALYX_CERTIFICATION_TEST_DATABASE_URL not configured",
)
def test_missing_optional_postgres_queue_does_not_poison_database_probe(monkeypatch) -> None:
    engine = create_engine(os.environ["CALYX_CERTIFICATION_TEST_DATABASE_URL"])
    monkeypatch.setattr("app.database.get_engine", lambda: engine)

    report = certification._production_observability(
        {
            "DATABASE_URL": "configured",
            "RENDER_GIT_COMMIT": "same-sha",
            "CALYX_EXPECTED_MAIN_COMMIT": "same-sha",
            "CALYX_GRAPH_VERSION": "test-graph",
        }
    )

    assert report["database"] == {
        "reachable": True,
        "dialect": "postgresql",
        "error_type": None,
    }
    assert report["queues"] == {
        "engineering_job_status_counts": None,
        "blocked_or_failed_jobs": None,
    }
    assert "ENGINEERING_QUEUE_METRICS_UNAVAILABLE" in report["blockers"]
    assert report["migration_state"] == {
        relation: "absent" for relation in certification.REASONING_RELATIONS
    }
    assert "REASONING_SCHEMA_INCOMPLETE" in report["blockers"]
    assert report["production_database_mutation"] is False
    assert report["production_knowledge_graph_mutation"] is False


def test_router_enables_live_probes_and_remains_protected() -> None:
    source = Path("runtime/calyx_core_certification.py").read_text(encoding="utf-8")
    assert "verify_owner_or_api_key" in source
    assert "build_calyx_core_certification(include_live_probes=True)" in source
    assert "automatic_publication\": False" in source
    assert "production_database_mutation\": False" in source
