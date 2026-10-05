from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from app.autonomy import coding_executor as ce
from app.provider_reservoir import routing as routing_module

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "oc_swarm_controller_coding", ROOT / "scripts" / "oc_swarm_controller.py"
)
assert _SPEC is not None and _SPEC.loader is not None
swarm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(swarm)

CODE_AUTHORING_BODY = "OC-SWARM-CAPABILITY: taxonomy-resolution\nOC-SWARM-WRITES: module-code"
EXECUTABLE_BODY = "OC-SWARM-PROVIDER-FREE: reconcile\nOC-SWARM-WRITES: module-exec"


def _issue(number, *labels, body=CODE_AUTHORING_BODY):
    return {
        "number": number,
        "title": f"P2 bounded work {number}",
        "body": body,
        "labels": list(labels),
        "state": "OPEN",
        "createdAt": "2026-09-01T00:00:00Z",
    }


def _plan(issues, **kwargs):
    return swarm.build_swarm_plan({"issues": issues, "now": "2026-10-01T00:00:00Z"}, **kwargs)


# ---- decision layer -------------------------------------------------------


def test_code_authoring_needs_a_coding_executor_but_executable_work_does_not():
    assert ce.needs_coding_executor(routing_module.route_task(_issue(1)))
    exec_issue = _issue(2, body=EXECUTABLE_BODY)
    assert not ce.needs_coding_executor(routing_module.route_task(exec_issue))
    undeclared = _issue(3, body="no capability stated")
    assert not ce.needs_coding_executor(routing_module.route_task(undeclared))


@pytest.mark.parametrize(
    ("labels", "blocked", "dependency", "state"),
    [
        (["oc-queued"], True, False, "provider_blocked"),
        (["oc-queued"], False, False, "queued"),
        (["oc-queued"], False, True, "dependency_blocked"),
        (["oc-queued", "oc-owner-gate"], False, False, "owner_gated"),
        (["oc-queued", "oc-scientific-gate"], False, False, "scientific_gated"),
        # A human hold outranks the provider gate: lifting the provider gate
        # must never release work a person is holding.
        (["oc-queued", "oc-owner-gate"], True, False, "owner_gated"),
        (["oc-queued", "oc-scientific-gate", "oc-owner-gate"], True, True, "scientific_gated"),
    ],
)
def test_dispatch_record_names_the_gate(labels, blocked, dependency, state):
    issue = _issue(10, *labels)
    record = ce.coding_dispatch_record(
        issue,
        routing_module.route_task(issue),
        provider_blocked=blocked,
        dependency_blocked=dependency,
    )
    assert record["state"] == state
    assert record["dispatchable"] is (state == "queued")
    assert (record["gate"] is None) is (state == "queued")


def _walk_to(state_name, maker="maker-session"):
    mission = ce.new_mission(1742, base_branch="oc-autonomous-integration", maker=maker)
    steps = [
        ("leased", {"lease_id": "L1"}),
        ("executing", {"run_id": "R1"}),
        ("implementation_complete", {"head_sha": "abc", "pull_request": 5}),
        ("testing", {"head_sha": "abc"}),
        ("certification", {"head_sha": "abc", "checks_passed": True}),
        (
            "integration_ready",
            {"head_sha": "abc", "checker": "checker-session", "target_branch": "oc-autonomous-integration"},
        ),
        ("integrated", {"merge_commit": "def", "target_branch": "oc-autonomous-integration"}),
        ("replenished", {"next_issue": 1743}),
    ]
    for name, evidence in steps:
        if mission["state"] == state_name:
            break
        mission = ce.advance(mission, name, **evidence)
    return mission


def test_full_lifecycle_produces_a_verifiable_chain():
    mission = _walk_to("replenished")
    assert mission["state"] == "replenished"
    assert [entry["to"] for entry in mission["history"]] == [
        "queued", "leased", "executing", "implementation_complete", "testing",
        "certification", "integration_ready", "integrated", "replenished",
    ]
    assert ce.verify_chain(mission)


def test_tampered_history_fails_verification():
    mission = _walk_to("integrated")
    mission["history"][2]["evidence"]["run_id"] = "forged"
    assert not ce.verify_chain(mission)


def test_states_cannot_be_skipped_or_asserted_without_evidence():
    mission = ce.new_mission(1, base_branch="oc-autonomous-integration", maker="m")
    with pytest.raises(ce.LifecycleError, match="ILLEGAL_TRANSITION"):
        ce.advance(mission, "integrated", merge_commit="x", target_branch="b")
    with pytest.raises(ce.LifecycleError, match="EVIDENCE_REQUIRED_FOR_LEASED"):
        ce.advance(mission, "leased")
    with pytest.raises(ce.LifecycleError, match="UNKNOWN_STATE"):
        ce.advance(mission, "done")


def test_checker_must_differ_from_maker_and_certify_the_exact_head():
    mission = _walk_to("certification", maker="same")
    with pytest.raises(ce.LifecycleError, match="CHECKER_MUST_DIFFER_FROM_MAKER"):
        ce.advance(mission, "integration_ready", head_sha="abc", checker="same",
                   target_branch="oc-autonomous-integration")
    with pytest.raises(ce.LifecycleError, match="CERTIFIED_HEAD_STALE"):
        ce.advance(mission, "integration_ready", head_sha="newer", checker="other",
                   target_branch="oc-autonomous-integration")


def test_a_new_push_voids_testing_and_certification():
    mission = _walk_to("implementation_complete")
    with pytest.raises(ce.LifecycleError, match="TESTING_HEAD_MISMATCH"):
        ce.advance(mission, "testing", head_sha="other")
    mission = _walk_to("testing")
    with pytest.raises(ce.LifecycleError, match="CERTIFICATION_HEAD_MISMATCH"):
        ce.advance(mission, "certification", head_sha="other", checks_passed=True)


@pytest.mark.parametrize("branch", ["main", "MASTER"])
def test_integration_to_a_protected_branch_is_never_a_lifecycle_step(branch):
    with pytest.raises(ce.LifecycleError, match="CODING_MISSION_BASE_PROTECTED"):
        ce.new_mission(1, base_branch=branch, maker="m")
    mission = _walk_to("certification")
    with pytest.raises(ce.LifecycleError, match="INTEGRATION_TARGET_PROTECTED"):
        ce.advance(mission, "integration_ready", head_sha="abc", checker="c", target_branch=branch)
    mission = _walk_to("integration_ready")
    with pytest.raises(ce.LifecycleError, match="INTEGRATION_TARGET_PROTECTED"):
        ce.advance(mission, "integrated", merge_commit="x", target_branch=branch)


def test_gates_release_only_to_queued_and_terminal_state_is_final():
    mission = ce.new_mission(1, base_branch="oc-autonomous-integration", maker="m")
    gated = ce.advance(mission, "provider_blocked", gate="no-authorised-coding-executor")
    with pytest.raises(ce.LifecycleError, match="ILLEGAL_TRANSITION"):
        ce.advance(gated, "leased", lease_id="L")
    assert ce.advance(gated, "queued")["state"] == "queued"
    with pytest.raises(ce.LifecycleError, match="MISSION_ALREADY_TERMINAL"):
        ce.advance(_walk_to("replenished"), "failed", reason="x")


def test_failure_requires_a_reason_and_can_requeue():
    mission = _walk_to("executing")
    with pytest.raises(ce.LifecycleError, match="EVIDENCE_REQUIRED_FOR_FAILED"):
        ce.advance(mission, "failed")
    failed = ce.advance(mission, "failed", reason="tests red on exact head")
    assert ce.advance(failed, "queued")["state"] == "queued"


# ---- controller integration ----------------------------------------------


def test_without_an_authorised_executor_code_authoring_is_provider_blocked_not_idle():
    plan = _plan([_issue(1742, "oc-queued")])
    assert plan["launch_count"] == 0
    assert plan["unstaffed_numbers"] == [1742]
    [record] = plan["coding_dispatch"]
    assert record["state"] == "provider_blocked"
    assert record["gate"] == "no-authorised-coding-executor"
    verdict = plan["homeostasis"]
    assert verdict["healthy_idle"] is False
    assert verdict["gates"]["coding_executor_blocked"] == [1742]


def test_with_an_authorised_executor_code_authoring_is_dispatched_to_the_completion_lane():
    plan = _plan([_issue(1742, "oc-queued")], coding_executor_available=True)
    assert plan["unstaffed_numbers"] == []
    assert plan["selected_numbers"] == [1742]
    assert plan["provider_launch_count"] == 1
    assert plan["provider_free_launch_count"] == 0
    [record] = plan["coding_dispatch"]
    assert record["state"] == "queued" and record["dispatchable"]
    assert plan["homeostasis"]["reason"] == "executing"
    assert "lane_refused" not in plan["homeostasis"]["gates"] or not plan["homeostasis"]["gates"]["lane_refused"]


def test_owner_gate_still_holds_code_authoring_when_the_executor_is_authorised():
    plan = _plan([_issue(1742, "oc-queued", "oc-owner-gate")], coding_executor_available=True)
    assert plan["launch_count"] == 0
    assert plan["coding_dispatch"][0]["state"] == "owner_gated"


def test_a_blocked_coding_lane_does_not_stop_executable_work():
    plan = _plan([_issue(1742, "oc-queued"), _issue(2, "oc-queued", body=EXECUTABLE_BODY)])
    assert plan["selected_numbers"] == [2]
    assert plan["coding_dispatch"][0]["state"] == "provider_blocked"
    assert plan["homeostasis"]["reason"] == "executing"


def test_coding_executor_and_provider_free_only_are_mutually_exclusive():
    with pytest.raises(ValueError):
        _plan([], provider_free_only=True, coding_executor_available=True)


def test_cli_flag_reaches_the_plan(tmp_path):
    import json

    snapshot = tmp_path / "s.json"
    snapshot.write_text(json.dumps({"issues": [_issue(1742, "oc-queued")], "now": "2026-10-01T00:00:00Z"}))
    out = tmp_path / "out"
    assert swarm.main(["--input", str(snapshot), "--coding-executor", "--github-output", str(out)]) == 0
    assert "provider_launch_count=1" in out.read_text()
