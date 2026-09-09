from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "orchid-swarm-controller.yml"


def test_swarm_workflow_uses_bounded_parallel_matrix():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "max-parallel: 12" in text
    assert "default: \"8\"" in text
    assert "oc_swarm_controller.py" in text
    assert "orchid-completion-lane.yml" in text


def test_swarm_workflow_targets_integration_not_main():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "INTEGRATION_BRANCH: oc-autonomous-integration" in text
    assert "ref: oc-autonomous-integration" in text
    assert "gh pr merge" not in text
    assert "production deploy: disabled" in text.lower()


def test_swarm_claims_only_queue_leases_and_reports_resources():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "oc-queued" in text
    assert "oc-running" in text
    assert "oc-owner-gate" in text
    assert "oc-blocked" in text
    assert "oc-runtime-backoff" in text
    assert "oc-repair-backoff" in text
    assert "Resource-aware worker lease claimed" in text
    assert "resource conflicts suppressed" in text
