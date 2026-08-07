from pathlib import Path

from app.design_planning.postgres_repository import PostgresDesignPlanningRepository
from app.scientific_interpretation.postgres_repository import PostgresInterpretationRepository


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_scientific_interpretation_table_registry_preserves_packet_entry():
    assert PostgresInterpretationRepository.TABLES["packet"] == (
        "evidence_packets",
        "packet_id",
        "packet_key",
    )


def test_design_planning_table_registry_preserves_product_request_entry():
    assert PostgresDesignPlanningRepository.TABLES["product_request"] == "product_requests"


def test_build_087b_full_suite_has_database_url_fallback():
    workflow = (REPO_ROOT / ".github/workflows/build-087b-validation.yml").read_text(
        encoding="utf-8"
    )
    full_suite = workflow.split("- name: Full backend suite", 1)[1].split(
        "- name: Compile, lint, and diff checks", 1
    )[0]
    assert "run: env -u TEST_DATABASE_URL python -m pytest -q" in full_suite
    assert "DATABASE_URL: postgresql://build087:build087_test_only@localhost:5432/build087_validation" in full_suite
