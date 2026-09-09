from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "orchid-swarm-controller.yml"


def test_v4_collects_closed_issues_for_dependency_resolution():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--state all" in text
    assert "oc_swarm_dependency_graph.py" in (
        ROOT / "scripts" / "oc_swarm_controller.py"
    ).read_text(encoding="utf-8")


def test_v4_has_bounded_self_refill():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "max_waves" in text
    assert 'default: "4"' in text
    assert "Dispatch bounded refill wave" in text
    assert "current >= maximum" in text
    assert "gh workflow run orchid-swarm-controller.yml" in text


def test_v4_refills_on_state_changes_and_periodic_pulse():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "*/5 * * * *"' in text
    assert "issues:" in text
    assert "types: [closed, reopened, labeled, unlabeled]" in text
    assert "pull_request:" in text
    assert "types: [closed]" in text


def test_v4_receipt_carries_dependencies_and_resources():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "{reads,writes,dependencies}" in text
    assert "[OC-SWARM-V4]" in text


def test_v4_does_not_merge_or_deploy():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "gh pr merge" not in text
    assert "production deploy: disabled" in text.lower()
