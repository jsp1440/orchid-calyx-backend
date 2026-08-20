"""The certification driver must never be able to manufacture a pass.

Every property here exists because the opposite would let AGENT-007 report
success without the governor having done anything:

- a governor that stalls must not exit 0;
- a transport failure must be distinguishable from a governor failure;
- an already-running persisted governor job may be reused only when its bounded
  repair authority matches the certification request;
- the driver must never call a mutating endpoint other than the two persisted
  governor endpoints.
"""

from __future__ import annotations

import json

import pytest

from scripts.calyx_agent_007_persisted_certify import (
    CERTIFICATION_MARKER,
    certify,
)

PATHS = ["tests/test_build_088e_publication_operational_readiness.py"]
CHECKS = ["BUILD-088E Validation"]
OBJECTIVE = f"Repair only {CERTIFICATION_MARKER}."


class Recorder:
    """Stand in for HTTP transport while preserving realistic endpoint shapes."""

    def __init__(self, script: list[dict], *, active_jobs: list[dict] | None = None):
        self.script = list(script)
        self.active_jobs = list(active_jobs or [])
        self.calls: list[tuple[str, str]] = []

    def __call__(self, base_url, api_key, method, path, payload=None):
        self.calls.append((method, path))
        if path == "/brain/engineering/status":
            return {"enabled": True}
        if path.startswith("/brain/engineering/completion-jobs?") and method == "GET":
            return {"jobs": self.active_jobs, "count": len(self.active_jobs), "mutating": False}
        if path.endswith("/completion-jobs") and method == "POST":
            return {"job_id": "job-1", "status": "queued"}
        if path == "/brain/engineering/completion-jobs/run-once":
            return {"executed": True, "job_id": "job-1"}
        if path.startswith("/brain/engineering/completion-jobs/job-1"):
            return self.script.pop(0) if self.script else {
                "state": "waiting_for_ci",
                "status": "queued",
            }
        if path.startswith("/brain/engineering/completion-jobs/job-existing"):
            return self.script.pop(0) if self.script else {
                "state": "waiting_for_ci",
                "status": "queued",
            }
        raise AssertionError(f"driver reached an unexpected endpoint: {method} {path}")


def _active_job(**overrides):
    job = {
        "job_id": "job-existing",
        "pull_request_number": 1043,
        "status": "running",
        "attempt_count": 0,
        "required_checks": CHECKS,
        "repair_paths": PATHS,
        "objective": OBJECTIVE,
        "repairs_authorized": True,
        "state": "waiting_for_ci",
    }
    job.update(overrides)
    return job


def _run(monkeypatch, script, *, active_jobs=None, recorder_cls=Recorder, **kwargs):
    recorder = recorder_cls(script, active_jobs=active_jobs)
    monkeypatch.setattr("scripts.calyx_agent_007_persisted_certify._call", recorder)
    monkeypatch.setattr("scripts.calyx_agent_007_persisted_certify.time.sleep", lambda _: None)
    defaults = {
        "base_url": "https://example.invalid",
        "api_key": "k",
        "pull_request": 1043,
        "paths": PATHS,
        "required_checks": CHECKS,
        "objective": OBJECTIVE,
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
    code, evidence, _ = _run(monkeypatch, [], max_steps=3)
    assert code != 0
    assert evidence.transitions[-1]["step"] == "exhausted"


def test_a_repair_limit_halt_is_reported_as_a_halt_not_a_pass(monkeypatch):
    code, evidence, _ = _run(monkeypatch, [
        {"state": "halted_repair_limit", "status": "dead_letter"}
    ])
    assert code == 3
    assert evidence.transitions[-1]["step"] == "halted"


def test_an_unsafe_pr_state_halt_is_reported_as_a_halt(monkeypatch):
    code, _, _ = _run(monkeypatch, [
        {"state": "halted_unsafe_pr_state", "status": "dead_letter"}
    ])
    assert code == 3


def test_a_job_blocked_on_authorization_halts_rather_than_looping(monkeypatch):
    code, evidence, _ = _run(monkeypatch, [
        {"state": "failed_repairable", "status": "blocked_approval",
         "error_code": "ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED"},
    ])
    assert code == 3
    assert evidence.transitions[-1]["error_code"] == "ENGINEERING_COMPLETION_REPAIR_AUTHORIZATION_REQUIRED"


def test_matching_active_job_is_reused_without_enqueue(monkeypatch):
    code, evidence, recorder = _run(
        monkeypatch,
        [{"state": "ready_for_merge", "status": "completed", "attempt_count": 1}],
        active_jobs=[_active_job()],
    )
    assert code == 0
    assert any(t["step"] == "reused_active_job" for t in evidence.transitions)
    assert not any(method == "POST" and path.endswith("/pull-requests/1043/completion-jobs")
                   for method, path in recorder.calls)


def test_marker_equivalent_objective_can_reuse_same_bounded_job(monkeypatch):
    code, evidence, _ = _run(
        monkeypatch,
        [{"state": "ready_for_merge", "status": "completed", "attempt_count": 1}],
        active_jobs=[_active_job(objective=f"Legacy wording: repair {CERTIFICATION_MARKER} only.")],
        objective=f"Current wording: repair {CERTIFICATION_MARKER}; touch nothing else.",
    )
    assert code == 0
    assert any(t["step"] == "reused_active_job" for t in evidence.transitions)


@pytest.mark.parametrize(
    "override",
    [
        {"repair_paths": ["app/main.py"]},
        {"required_checks": ["Some Other Check"]},
        {"repairs_authorized": False},
        {"objective": "Repair some unrelated defect."},
    ],
)
def test_conflicting_active_job_is_never_reused(monkeypatch, override):
    code, evidence, recorder = _run(monkeypatch, [], active_jobs=[_active_job(**override)])
    assert code == 3
    assert evidence.transitions[-1]["step"] == "active_job_authorization_conflict"
    assert not any(path == "/brain/engineering/completion-jobs/run-once" for _, path in recorder.calls)


def test_running_job_conflict_race_reuses_matching_persisted_job(monkeypatch):
    class RaceRecorder(Recorder):
        def __init__(self, script, *, active_jobs=None):
            super().__init__(script, active_jobs=[])
            self.list_reads = 0

        def __call__(self, base_url, api_key, method, path, payload=None):
            if path.startswith("/brain/engineering/completion-jobs?") and method == "GET":
                self.calls.append((method, path))
                self.list_reads += 1
                if self.list_reads == 1:
                    return {"jobs": [], "count": 0, "mutating": False}
                job = _active_job()
                return {"jobs": [job], "count": 1, "mutating": False}
            if path.endswith("/completion-jobs") and method == "POST":
                self.calls.append((method, path))
                raise RuntimeError(
                    'HTTP_422:{"detail":{"code":"ENGINEERING_COMPLETION_RUNNING_JOB_CONFLICT"}}'
                )
            return super().__call__(base_url, api_key, method, path, payload)

    code, evidence, _ = _run(
        monkeypatch,
        [{"state": "ready_for_merge", "status": "completed", "attempt_count": 1}],
        recorder_cls=RaceRecorder,
    )
    assert code == 0
    assert any(t["step"] == "reused_active_job_after_enqueue_race" for t in evidence.transitions)


def test_running_job_conflict_race_refuses_mismatched_job(monkeypatch):
    class RaceConflictRecorder(Recorder):
        def __init__(self, script, *, active_jobs=None):
            super().__init__(script, active_jobs=[])
            self.list_reads = 0

        def __call__(self, base_url, api_key, method, path, payload=None):
            if path.startswith("/brain/engineering/completion-jobs?") and method == "GET":
                self.calls.append((method, path))
                self.list_reads += 1
                if self.list_reads == 1:
                    return {"jobs": [], "count": 0, "mutating": False}
                job = _active_job(repair_paths=["app/main.py"])
                return {"jobs": [job], "count": 1, "mutating": False}
            if path.endswith("/completion-jobs") and method == "POST":
                self.calls.append((method, path))
                raise RuntimeError(
                    'HTTP_422:{"detail":{"code":"ENGINEERING_COMPLETION_RUNNING_JOB_CONFLICT"}}'
                )
            return super().__call__(base_url, api_key, method, path, payload)

    code, evidence, _ = _run(monkeypatch, [], recorder_cls=RaceConflictRecorder)
    assert code == 3
    assert evidence.transitions[-1]["step"] == "running_job_conflict"


def test_the_driver_only_ever_touches_governor_endpoints(monkeypatch):
    _, _, recorder = _run(monkeypatch, [
        {"state": "ready_for_merge", "status": "completed"}
    ])
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
                self.calls.append((method, path))
                return {"detail": {"code": "CALYX_ENGINEERING_DISABLED"}}
            return super().__call__(base_url, api_key, method, path, payload)

    code, evidence, _ = _run(monkeypatch, [], recorder_cls=NoJob)
    assert code == 2
    assert evidence.transitions[-1]["step"] == "enqueue_failed"


def test_a_transport_failure_is_not_reported_as_a_governor_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("CERTIFICATION_ENDPOINT_UNREACHABLE:blocked")

    monkeypatch.setattr("scripts.calyx_agent_007_persisted_certify._call", boom)
    with pytest.raises(RuntimeError, match="CERTIFICATION_ENDPOINT_UNREACHABLE"):
        certify(
            base_url="https://example.invalid",
            api_key="k",
            pull_request=1043,
            paths=PATHS,
            required_checks=CHECKS,
            objective=OBJECTIVE,
            max_steps=1,
            poll_seconds=0,
        )


def test_every_step_is_recorded_with_the_persisted_row_not_just_the_worker_reply(monkeypatch):
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
