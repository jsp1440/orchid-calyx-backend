from app.main import app
from runtime.autonomous_orchestrator import DefaultTaskExecutor
from runtime.constitutional_orchestrator import orchestrator


def test_high_risk_policy_requires_review_even_at_low_requested_level():
    result = orchestrator.evaluate_action(
        mission_id="engineering",
        action="delete production records",
        requested_autonomy_level=1,
        evidence=["operator request"],
        reversible=True,
        provenance_available=True,
    )

    decision = result["decision"]
    assert decision["status"] == "review_required"
    assert decision["risk_level"] == "high"
    assert "owner_approval_for_high_risk" in decision["constitutional_policies"]
    assert result["governance_question"]["status"] == "open"


def test_orchestrator_approval_gate_matches_constitutional_high_risk_terms():
    executor = DefaultTaskExecutor()

    assert executor.risky_action("change_target", {}) == "change_target"
    assert executor.risky_action("change_schedule", {}) == "change_schedule"
    assert executor.risky_action("retire", {}) == "retire"
    assert executor.risky_action("restore", {}) == "restore"
    assert executor.risky_action("frontend_integration_audit", {"cross_repository": True}) == "cross_repository"
    assert executor.risky_action("backend_health_check", {"operation": "credential_sensitive"}) == "credential_sensitive"


def test_integrated_route_inventory_has_no_duplicate_paths_for_new_runtime_families():
    method_paths = [
        (tuple(sorted(route.methods or [])), route.path)
        for route in app.routes
        if route.path.startswith(("/api/harvesters", "/api/orchestrator", "/api/runner/constitutional"))
    ]

    assert len(method_paths) == len(set(method_paths))
    paths = {path for _, path in method_paths}
    assert "/api/harvesters" in paths
    assert "/api/orchestrator/health" in paths
    assert "/api/runner/constitutional/status" in paths
