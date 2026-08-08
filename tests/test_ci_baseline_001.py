from pathlib import Path

from app.design_planning.postgres_repository import PostgresDesignPlanningRepository
from app.scientific_interpretation.postgres_repository import (
    PostgresInterpretationRepository,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_scientific_interpretation_table_registry_preserves_packet_entry():
    assert PostgresInterpretationRepository.TABLES["packet"] == (
        "evidence_packets",
        "packet_id",
        "packet_key",
    )


def test_design_planning_table_registry_preserves_product_request_entry():
    assert PostgresDesignPlanningRepository.TABLES["product_request"] == "product_requests"


def test_build_087b_repository_wide_suite_is_blocking_with_database_fallback():
    workflow = (REPO_ROOT / ".github/workflows/build-087b-validation.yml").read_text(
        encoding="utf-8"
    )
    suite = workflow.split("- name: Repository-wide backend suite", 1)[1].split(
        "- name: Scientific interpretation package Ruff diagnostic", 1
    )[0]
    assert "continue-on-error: true" not in suite
    assert "env -u TEST_DATABASE_URL python -m pytest -q" in suite
    assert "--ignore=tests/calyx_certification/test_deterministic_failure_round2.py" in suite
    assert "--ignore=tests/test_calyx_journalism_mvp_001.py" in suite
    assert (
        "DATABASE_URL: postgresql://build087:build087_test_only@localhost:5432/"
        "build087_validation?sslmode=disable"
    ) in suite


def test_build_087b_validation_installs_async_pytest_support():
    workflow = (REPO_ROOT / ".github/workflows/build-087b-validation.yml").read_text(
        encoding="utf-8"
    )
    assert "pytest pytest-asyncio httpx ruff" in workflow
