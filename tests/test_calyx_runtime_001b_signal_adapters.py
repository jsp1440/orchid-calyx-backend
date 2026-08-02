from runtime.self_audit_adapters import (
    backend_health_signals,
    github_ci_signals,
    harvester_signals,
    queue_signals,
)


def test_github_adapter_reports_failed_checks_and_stale_prs():
    signals = github_ci_signals({"failing_checks": 2, "stale_pull_requests": 1})
    assert [signal.status for signal in signals] == ["failed", "stale"]
    assert signals[0].details["count"] == 2


def test_backend_adapter_is_critical_when_unhealthy():
    signal = backend_health_signals({"healthy": False, "http_status": 503})[0]
    assert signal.status == "degraded"
    assert signal.severity == "critical"


def test_queue_and_harvester_adapters_are_read_only_normalizers():
    queue = queue_signals({"failed": 1, "running": 3, "stuck": 2})
    harvesters = harvester_signals({"stale_sources": 4, "errors": 1})
    assert [signal.status for signal in queue] == ["failed", "blocked"]
    assert [signal.status for signal in harvesters] == ["stale", "error"]
