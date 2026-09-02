"""Fail-closed contract for the Calyx MVP staging readiness workflow."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/calyx-mvp-staging-readiness.yml")
PRODUCTION_HOST = "orchid-calyx-backend.onrender.com"


def source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_staging_readiness_is_manual_and_staging_scoped():
    text = source()
    assert "workflow_dispatch:" in text
    assert "environment: staging" in text
    assert "CALYX_STAGING_BACKEND_URL" in text
    assert "CALYX_STAGING_OWNER_ACCESS_CODE" in text


def test_staging_readiness_rejects_the_canonical_production_backend():
    text = source()
    rejection = (
        '[[ "$CALYX_STAGING_BACKEND_URL" != *'
        f'"{PRODUCTION_HOST}"* ]]'
    )
    assert rejection in text
    assert "Production backend URL is forbidden" in text


def test_staging_readiness_is_read_only_and_submits_no_provider_turn():
    text = source()
    assert "/api/scientific-interpretation/synthesis/health" in text
    taxonomy_status = (
        "/api/mission-control/taxonomy/hassler-release-status"
    )
    assert taxonomy_status in text
    assert "/api/calyx/speak/conversations" not in text

    without_boundary_receipts = text.lower().replace(
        "no taxonomy activation",
        "",
    ).replace(
        "no knowledge graph publication",
        "",
    )
    assert "activate" not in without_boundary_receipts
    assert "publish" not in without_boundary_receipts
    assert "paid_calyx_turn_submitted: false" in text
    assert "mutation_performed: false" in text


def test_staging_readiness_has_least_privilege_and_bounded_runtime():
    text = source()
    assert "permissions:\n  contents: read" in text
    assert "timeout-minutes: 10" in text
    assert "cancel-in-progress: false" in text
