from __future__ import annotations

from app.main import app


def test_phase_3_product_routes_are_registered() -> None:
    paths = {route.path for route in app.routes}
    assert "/brain/orchestrator/product/status" in paths
    assert "/brain/orchestrator/product/programs/phase-3-demo" in paths
    assert "/brain/orchestrator/product/workers/jobs/{program_job_id}/complete" in paths
