"""The certification driver must never be able to manufacture a pass.

Every property here exists because the opposite would let AGENT-007 report
success without the governor having done anything:

- a governor that stalls must not exit 0;
- a transport failure must be distinguishable from a governor failure, or an
  unreachable service reads as a broken governor (and vice versa, which is
  worse);
- the driver must never call a mutating endpoint other than the two the
  governor itself exposes - if the driver could repair, merge, or advance
  anything on its own, the certification would be measuring the driver.
"""

from __future__ import annotations

import json

import pytest

from scripts.calyx_agent_007_persisted_certify import certify

PATHS = ["tests/test_build_088e_publication_operational_readiness.py"]
CHECKS = ["BUILD-088E Validation"]


class Recorder:
    """Stands in for the HTTP transport, not for the governor.

    The governor's decisions are the *inputs* to these cases. What is under
    test is the driver's reporting, which is why every response here is a
    literal the real service could return.
    """

    def __init__(self, script: list[dict]):
        self.script = list(script)
        self.calls: list[tuple[str, str]] = []

    def __call__(self, base_url, api_key, method, path, payload=None):
        self.calls.append((method, path))
        if path == "/brain/engineering/status":
            return {"enabled": True}
        if path.endswith("/completion-jobs") and method == "POST":
            return {"job_id": "job-1", "status": "queued"}
        if path == "/brain/engineering/completion-jobs/run-once":
            return {"executed": True, "job_id": "job-1"}
        if path.startswith("/brain/engineering/completion-jobs/job-1"):
            return self.script.pop(0) if self.script else {"state": "waiting_for_ci", "status": "queued"}
        raise AssertionError(f"driver reached an unexpected endpoint: {method} {path}")


def _run(monkeypatch, script, **kwargs):
    recorder = Recorder(script)
    monkeypatch.setattr("scripts.calyx_agent_007_persisted_certify._call", recorder)
    monkeypatch.setattr("scripts.calyx_agent_007_persisted_certify.time.sleep", lambda _: None)
    defaults = {
        "base_url": "https://example.invalid",
        "api_key": "k",
        "pull_request": 1043,
        "paths": PATHS,
        "required_checks": CHECKS,
        "objective": "Repair the certification marker only.",
        "max_steps": 5,
        "poll_seconds": 0,
    }
    defaults.update(kwargs)
    code, evidence = certify(**defaults)
    return code, evidence, recorder


def test_reaching_ready_for_merge_is_the_only_success(monkeypatch):
    code, evidence, _ = _run(monkeypatch, [
        {"state": "waiting_for_ci", "status": "queued", "attempt_count": 0},
        {"state": "repair_committed", "status": "queued", "attempt_count": 1},
        {"state": "ready_for_merge", "status": "completed", "attempt_count": 1,
         "autonomous_merge": False, "deployment": False},
    ])
    assert code == 0
    states = [t.get("state") for t in evidence.transitions if "state" in t]
    assert "ready_for_merge" in states
    assert any(t["step"] == "terminated" for t in evidence.transitions)


def test_a_governor_that_never_finishes_does_not_report_success(monkeypatch):
    """The stall that started this whole investigation."""
    code, evidence, _ = _run(monkeypatch, [], max_steps=3)
    assert code != 0
    assert evidence.transitions[-1]["step"] == "exhausted"


def test_a_repair_limit_halt_is_reported_as_a_halt_not_a_pass(monkeypatch):
    code, evidence, _ = _run(monkeypatch, [{"state": "halted_repair_limit", "status": "dead_letter"}])
    assert code == 3
    assert evidence.transitions[-1]["step"] == "halted"


def test_an_unsafe_pr_state_halt_is_reported_as_a_halt(monkeypatch):
    code, _, _ = _run(monkeypatch, [{"state": "halted_unsafe_pr_state", "status": "dead_letter"}])
    assert code == 3


def test_a_job_blocked_on_authorization_halts_rather_than_looping(monkeypatch):
    code, evidence, _ = _run(monkeypatch, [
        {"state": "failed_repairable", "status": "blocked_approval",
         "error_code": "ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED"},
    ])
    assert code == 3
    assert evidence.transitions[-1]["error_code"] == "ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED"


def test_the_driver_only_ever_touches_governor_endpoints(monkeypatch):
    """If the driver could act, the certification would be measuring the driver."""
    _, _, recorder = _run(monkeypatch, [{"state": "ready_for_merge", "status": "completed"}])
    mutating = [(m, p) for m, p in recorder.calls if m != "GET"]
    assert all(
        p.endswith("/completion-jobs") or p == "/brain/engineering/completion-jobs/run-once"
        for _, p in mutating
    ), mutating
    assert not any("/repair" in p or "/merge" in p or "/execute" in p for _, p in recorder.calls)


def test_an_enqueue_that_returns_no_job_id_fails_loudly(monkeypatch):
    class NoJob(Recorder):
        def __call__(self, base_url, api_key, method, path, payload=None):
            if path.endswith("/completion-jobs") and method == "POST":
                return {"detail": {"code": "CALYX_ENGINEERING_DISABLED"}}
            return super().__call__(base_url, api_key, method, path, payload)

    recorder = NoJob([])
    monkeypatch.setattr("scripts.calyx_agent_007_persisted_certify._call", recorder)
    code, evidence = certify(
        base_url="https://example.invalid", api_key="k", pull_request=1043, paths=PATHS,
        required_checks=CHECKS, objective="o", max_steps=2, poll_seconds=0,
    )
    assert code == 2
    assert evidence.transitions[-1]["step"] == "enqueue_failed"


def test_a_transport_failure_is_not_reported_as_a_governor_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("CERTIFICATION_ENDPOINT_UNREACHABLE:blocked")

    monkeypatch.setattr("scripts.calyx_agent_007_persisted_certify._call", boom)
    with pytest.raises(RuntimeError, match="CERTIFICATION_ENDPOINT_UNREACHABLE"):
        certify(
            base_url="https://example.invalid", api_key="k", pull_request=1043, paths=PATHS,
            required_checks=CHECKS, objective="o", max_steps=1, poll_seconds=0,
        )


def test_every_step_is_recorded_with_the_persisted_row_not_just_the_worker_reply(monkeypatch):
    """Durable evidence means the row, not the worker's own account of itself."""
    _, evidence, _ = _run(monkeypatch, [
        {"state": "waiting_for_ci", "status": "queued", "attempt_count": 0},
        {"state": "ready_for_merge", "status": "completed", "attempt_count": 1},
    ])
    steps = [t for t in evidence.transitions if t["step"].startswith("step_")]
    assert steps
    for step in steps:
        assert "persisted_job" in step
        assert "run_once" in step
    json.dumps({"transitions": evidence.transitions}, default=str)
