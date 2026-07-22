from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.design_planning.my_conservatory import MyConservatoryPlanningDemonstration
from app.design_planning.postgres_repository import PostgresDesignPlanningRepository
from app.design_planning.service import DesignPlanningService
from tests.test_build_090c_my_conservatory_planning import build_089_adapter


DATABASE_URL = os.getenv("BUILD_090C_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="BUILD_090C_DATABASE_URL unavailable"
)


def test_my_conservatory_artifacts_reconstruct_from_postgresql_16():
    import psycopg

    migration = Path(
        "migrations/090b_design_reasoning_interface_planning_foundation.sql"
    ).read_text()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        conn.execute(migration)
    repository = PostgresDesignPlanningRepository(DATABASE_URL)
    service = DesignPlanningService(repository, build_089_adapter())
    first = MyConservatoryPlanningDemonstration(service).execute()
    second = MyConservatoryPlanningDemonstration(service).execute()
    assert first == second
    request = repository.get("product_request", first.product_request_id)
    plan = repository.get("plan", first.review_plan_id)
    assert request.version == 1 and len(request.requirements) == 18
    assert plan.version == 2 and plan.lifecycle_state.value == "REVIEW_REQUIRED"
    assert len(repository.history("reasoning", "my-conservatory:navigation")) == 1
    assert len(repository.audits()) == first.audit_event_count
