import app.main as main
from app.main import app
from runtime.autonomous_orchestrator import DefaultTaskExecutor
from runtime.constitutional_orchestrator import orchestrator

from fastapi.testclient import TestClient


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


def test_autonomous_runtime_does_not_start_by_default(monkeypatch):
    for key in main.RUNTIME_ENABLE_FLAGS + main.RUNTIME_DISABLE_FLAGS:
        monkeypatch.delenv(key, raising=False)

    assert main.autonomous_runtime_config_blocker() is None
    assert main.autonomous_runtime_enabled_by_config() is False


def test_autonomous_runtime_requires_explicit_true_enable(monkeypatch):
    for key in main.RUNTIME_ENABLE_FLAGS + main.RUNTIME_DISABLE_FLAGS:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("OC_RUNNER_AUTOLOOP", "true")
    assert main.autonomous_runtime_enabled_by_config() is True

    monkeypatch.setenv("CALYX_AUTONOMOUS_DISABLED", "true")
    assert main.autonomous_runtime_enabled_by_config() is False


def test_state_changing_runtime_routes_fail_closed_without_api_key(monkeypatch):
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    client = TestClient(app)
    evaluate_body = {
        "mission_id": "engineering",
        "action": "test write",
        "requested_autonomy_level": 1,
        "evidence": ["test"],
    }
    task_body = {"task_type": "backend_health_check", "title": "test task", "payload": {}, "priority": 1}
    routes = [
        ("post", "/api/runner/run-once", None),
        ("post", "/api/runner/execute-next", None),
        ("post", "/api/runner/execute-all", None),
        ("post", "/api/runner/autonomous-cycle", None),
        ("post", "/api/runner/autonomous-start", None),
        ("post", "/api/runner/autonomous-stop", None),
        ("post", "/api/runner/start", None),
        ("post", "/api/runner/stop", None),
        ("post", "/api/runner/restart", None),
        ("post", "/api/runner/seed-missions", None),
        ("post", "/api/runner/rebuild-plan", None),
        ("post", "/api/runner/execute", None),
        ("post", "/api/runner/execute/test-module", None),
        ("post", "/api/runner/retry/1", None),
        ("post", "/api/runner/cancel/1", None),
        ("post", "/api/runner/discover", None),
        ("post", "/api/runner/rebuild", None),
        ("post", "/api/runner/discovery-snapshots/capture", None),
        ("post", "/api/runner/knowledge-gaps/discover", None),
        ("post", "/api/runner/knowledge-diagnostics/discover", None),
        ("post", "/api/runner/connector-plans/generate", None),
        ("post", "/api/runner/connector-scaffolds/build", None),
        ("post", "/api/runner/connector-scaffolds/build/test-plan", None),
        ("post", "/api/runner/constitutional/evaluate", evaluate_body),
        ("post", "/api/runtime/constitutional/evaluate", evaluate_body),
        ("post", "/api/orchestrator/seed", None),
        ("post", "/api/orchestrator/tasks", task_body),
        ("post", "/api/orchestrator/tasks/1/approve", None),
        ("post", "/api/orchestrator/run-once", None),
        ("post", "/api/harvesters/gbif/pause", None),
    ]

    for method, path, body in routes:
        response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
        assert response.status_code == 401, path


def test_read_models_expose_disabled_allowed_actions_without_secrets(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", "test-secret")
    client = TestClient(app)

    runner = client.get("/api/runner/health")
    assert runner.status_code == 200
    assert runner.json()["allowedActions"]["startRuntime"]["allowed"] is False
    assert "test-secret" not in runner.text

    harvesters = client.get("/api/harvesters")
    assert harvesters.status_code == 200
    first = harvesters.json()["harvesters"][0]
    assert first["allowedActions"]["changeSchedule"]["auth"] == "api_key_required"
    assert first["allowedActions"]["changeSchedule"]["allowed"] is False
    assert "test-secret" not in harvesters.text
