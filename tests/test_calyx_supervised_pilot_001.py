import json

from runtime.supervised_pilot import approved_pilot_task, run_supervised_pilot


def test_pilot_is_disabled_without_explicit_environment_gate(monkeypatch):
    monkeypatch.delenv("CALYX_SUPERVISED_PILOT_ENABLED", raising=False)

    assert approved_pilot_task() is None
    result = json.loads(run_supervised_pilot())
    assert result == {"executed": False, "package": None, "reason": "pilot-disabled"}


def test_enabled_pilot_prepares_one_draft_only_package(monkeypatch):
    monkeypatch.setenv("CALYX_SUPERVISED_PILOT_ENABLED", "true")

    result = json.loads(run_supervised_pilot())

    assert result["executed"] is True
    assert result["reason"] == "draft-package-prepared-no-github-write"
    assert result["package"]["draft"] is True
    assert result["package"]["base_branch"] == "main"
    assert result["package"]["evidence"]["validation_results"] == {
        "draft-only": True,
        "no-connector-execution": True,
        "pilot-policy": True,
    }
    assert "merge" in result["package"]["evidence"]["prohibited_actions"]
    assert "deploy" in result["package"]["evidence"]["prohibited_actions"]
