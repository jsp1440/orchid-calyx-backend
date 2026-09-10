from pathlib import Path


WORKFLOW = Path(".github/workflows/orchid-continuous-completion.yml")


def test_legacy_scheduler_is_a_manual_swarm_redirect_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "push:" not in text
    assert "pull_request:" not in text
    assert "issues:" not in text
    assert "oc_portfolio_scheduler.py" not in text
    assert "orchid-completion-lane.yml" not in text
    assert "gh workflow run orchid-swarm-controller.yml" in text
    assert "--ref main" in text
