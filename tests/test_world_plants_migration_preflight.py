from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.routers.taxonomy_releases import create_taxonomy_release_router
from runtime.world_plants_migration_preflight import (
    MIGRATION_ID,
    inspect_world_plants_migration,
    migration_sha256,
)

TEST_DATABASE_URL = os.getenv("WORLD_PLANTS_STAGING_TEST_DATABASE_URL")


@pytest.fixture()
def engine():
    if not TEST_DATABASE_URL:
        pytest.skip("WORLD_PLANTS_STAGING_TEST_DATABASE_URL is not configured")
    target = create_engine(TEST_DATABASE_URL)
    with target.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS taxonomy_pipeline CASCADE"))
    yield target
    with target.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS taxonomy_pipeline CASCADE"))
    target.dispose()


def _migration_sql() -> str:
    return Path("migrations/107_world_plants_release_staging.sql").read_text(
        encoding="utf-8"
    )


def test_preflight_reports_governed_migration_required_without_mutating_schema(engine):
    before = inspect_world_plants_migration(engine)
    after = inspect_world_plants_migration(engine)

    assert before == after
    assert before["migration_id"] == MIGRATION_ID
    assert len(before["migration_sha256"]) == 64
    assert before["migration_sha256"] == migration_sha256()
    assert before["state"] == "migration_required"
    assert before["schema_exists"] is False
    assert before["schema_complete"] is False
    assert before["next_job"]["job"] == "apply_migration_107"
    assert before["next_job"]["requires_owner_approval"] is True
    assert before["next_job"]["governance_boundary"] == "production_database_migration"
    assert before["read_only"] is True
    assert before["no_schema_mutation"] is True

    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT to_regnamespace('taxonomy_pipeline') IS NULL")
            ).scalar_one()
            is True
        )


def test_migration_is_double_apply_idempotent_and_preflight_verifies_schema(engine):
    migration = _migration_sql()
    with engine.begin() as connection:
        connection.exec_driver_sql(migration)
        connection.exec_driver_sql(migration)

    report = inspect_world_plants_migration(engine)

    assert report["state"] == "migration_verified"
    assert report["schema_exists"] is True
    assert report["schema_complete"] is True
    assert report["missing_tables"] == []
    assert report["missing_columns"] == {}
    assert report["missing_indexes"] == []
    assert report["next_job"]["job"] == "run_taxonomy_staging_smoke"
    assert report["next_job"]["requires_owner_approval"] is True
    assert report["automatic_promotion"] is False


def test_preflight_fails_closed_on_partial_schema(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE SCHEMA taxonomy_pipeline")
        connection.exec_driver_sql(
            "CREATE TABLE taxonomy_pipeline.releases (release_id text PRIMARY KEY)"
        )

    report = inspect_world_plants_migration(engine)

    assert report["state"] == "partial_schema_detected"
    assert "staged_taxa" in report["missing_tables"]
    assert "source_sha256" in report["missing_columns"]["releases"]
    assert report["next_job"]["job"] == "review_partial_taxonomy_schema"
    assert report["next_job"]["requires_owner_approval"] is True
    assert report["next_job"]["governance_boundary"] == "production_database_repair"


def test_owner_gated_migration_preflight_route_can_report_without_exposing_database_details():
    expected = {
        "migration_id": MIGRATION_ID,
        "migration_sha256": "a" * 64,
        "state": "migration_required",
        "read_only": True,
        "automatic_promotion": False,
        "no_schema_mutation": True,
    }

    app = FastAPI()
    app.include_router(
        create_taxonomy_release_router(
            require_owner=lambda: {"owner": True},
            get_migration_preflight=lambda: expected,
        )
    )
    client = TestClient(app)

    response = client.get("/api/mission-control/taxonomy/migration-preflight")

    assert response.status_code == 200
    assert response.json() == expected
