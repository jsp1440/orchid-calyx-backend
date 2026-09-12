"""Exercise the GitHub receipt adapter and the actual observer CLI boundary."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from scripts import oc_control_plane_health as health

ROOT = Path(__file__).resolve().parents[1]
REPO = "jsp1440/orchid-calyx-backend"
PREFIX = f"repos/{REPO}/"
SHA = "a" * 40
NOW = datetime(2026, 9, 12, 4, tzinfo=timezone.utc)
FINGERPRINT = "b" * 16


def evidence():
    return {
        "git/ref/heads/oc-autonomous-integration": {"object": {"sha": SHA}},
        "git/ref/heads/main": {"object": {"sha": "c" * 40}},
        "issues?state=open&per_page=100&page=1": [],
        "pulls?state=open&base=oc-autonomous-integration&per_page=100&page=1": [],
        "actions/runs/42": {
            "id": 42, "repository": {"full_name": REPO}, "status": "completed",
            "conclusion": "success", "head_sha": SHA,
            "head_branch": "oc-autonomous-integration",
            "path": ".github/workflows/orchid-swarm-controller.yml",
        },
        "actions/runs/42/jobs?per_page=100&page=1": {"jobs": [
            {"runner_id": 1, "conclusion": "success", "steps": [{"conclusion": "success"}]},
        ]},
    }


def observe(data, **kwargs):
    def read(endpoint):
        assert endpoint.startswith(PREFIX)
        return copy.deepcopy(data[endpoint.removeprefix(PREFIX)])

    return health.collect_github_snapshot(REPO, 42, read_json=read, now=NOW, **kwargs)


def issue(number, labels):
    return {
        "number": number, "labels": labels, "state": "open",
        "updated_at": "2026-09-12T03:30:00Z",
        "body": "PRIVATE SOURCE TEXT MUST NOT BE PUBLISHED",
    }


def add_issue(data, row, comments=()):
    row["comments"] = len(comments)
    data["issues?state=open&per_page=100&page=1"].append(row)
    data[f"issues/{row['number']}"] = row
    data[f"issues/{row['number']}/comments?per_page=100&page=1"] = list(comments)


def claim(number=1, created="2026-09-12T03:30:00Z"):
    return {
        "id": number, "created_at": created, "user": {"login": "github-actions[bot]"},
        "body": '[OC-SWARM-V4] Dependency/resource lease claimed: `{"reads": [], "writes": ["literature"]}`.',
    }


def started():
    return {"body": f"[OC-AUTO] Completion worker started; packet={FINGERPRINT}. Run https://github.com/{REPO}/actions/runs/43."}


def test_real_receipt_shapes_produce_consistency_without_claiming_readiness():
    data = evidence()
    add_issue(data, issue(1, ["oc-running"]), [claim(), started()])
    receipt = health.build_health(observe(data))
    assert receipt["healthy"] is True
    assert receipt["contract_snapshot"]["leases"][0]["age_seconds"] == 1800
    assert receipt["contract_snapshot"]["provider"] == {"status": "no_api", "disabled": True}
    assert receipt["contract_snapshot"]["integration"]["ready"] == health.UNKNOWN
    assert receipt["last_successful_exact_head_validation"] == health.UNKNOWN
    assert "PRIVATE SOURCE TEXT" not in json.dumps(receipt)


def test_provider_permission_is_not_provider_health():
    snapshot = observe(evidence(), no_api_mode="false")
    assert snapshot["provider"] == {"status": health.UNKNOWN, "disabled": False}


def test_inconsistent_real_receipts_fail_canonical_contract():
    data = evidence()
    add_issue(data, issue(1, ["oc-running", "oc-queued", "oc-repair-backoff"]), [claim(), started(), claim(2), started()])
    receipt = health.build_health(observe(data))
    assert receipt["healthy"] is False
    assert {
        "multiple_executable_states", "executable_parked_conflict",
        "running_lease_cardinality", "duplicate_dispatch_fingerprint",
    } <= {v["type"] for v in receipt["contract_health"]["violations"]}


def test_running_label_alone_is_not_a_durable_lease():
    data = evidence()
    add_issue(data, issue(1, ["oc-running"]))
    report = health.build_health(observe(data))["contract_health"]
    assert report["healthy"] is False
    assert report["violations"] == [{"type": "running_lease_cardinality", "issue": 1, "active_leases": 0}]


def test_claim_does_not_invent_missing_material_fingerprint():
    data = evidence()
    add_issue(data, issue(1, ["oc-running"]), [claim()])
    snapshot = observe(data)
    assert snapshot["leases"][0]["material_fingerprint"] is None
    assert health.build_health(snapshot)["healthy"] is False


def test_released_receipts_are_not_resurrected_as_orphans():
    data = evidence()
    add_issue(data, issue(1, ["oc-blocked"]), [claim(), started(), {
        "body": "[OC-AUTO] Lane delivered/updated integration PR #3, dispatched independent backend validation, and released its execution slot."
    }])
    assert observe(data)["leases"] == []


@pytest.mark.parametrize("body", [
    "[OC-AUTO] Provider execution did not produce verifiable model execution evidence (classification=provider_failure). Parked in oc-runtime-backoff; no automatic paid retry.",
    "[OC-AUTO] Claude reached the bounded task/turn ceiling. Provider runtime remains healthy; issue moved to oc-repair and the global circuit stays closed.",
    "[OC-AUTO] Durable PR #3 exists, but validation dispatch failed. Kept in oc-validating; scheduler will retry validation without redispatching a model.",
])
def test_real_lane_failure_settlements_retire_old_claims(body):
    data = evidence()
    add_issue(data, issue(1, ["oc-blocked"]), [claim(), started(), {"body": body}])
    assert observe(data)["leases"] == []


@pytest.mark.parametrize("settled", [True, False])
def test_large_comment_history_uses_bounded_latest_window(monkeypatch, settled):
    monkeypatch.setattr(health, "MAX_PAGES", 1)
    data = evidence()
    row = issue(1, ["oc-blocked"])
    add_issue(data, row)
    row["comments"] = 501
    data["issues/1/comments?per_page=100&page=6"] = [
        {"body": "[OC-AUTO] Lane delivered and released its execution slot." if settled else "Historical note"},
    ]
    receipt = health.build_health(observe(data))
    assert receipt["healthy"] is settled
    assert receipt["observation_complete"] is settled


def test_stale_orphan_receipt_survives_for_reconciliation():
    data = evidence()
    add_issue(data, issue(1, ["oc-blocked"]), [claim(created="2026-09-12T01:00:00Z"), started()])
    snapshot = observe(data)
    assert snapshot["stale_lease_count"] == 1
    assert {"stale_lease", "orphan_active_lease"} <= {
        v["type"] for v in health.build_health(snapshot)["contract_health"]["violations"]
    }


def test_explicit_same_repository_pr_link_supplies_exact_head_only():
    data = evidence()
    add_issue(data, issue(1, ["oc-validating"]))
    data["pulls?state=open&base=oc-autonomous-integration&per_page=100&page=1"] = [
        {"number": 3, "head": {"sha": SHA}, "body": "OC-AUTO-ISSUE: #1\nPrivate findings"},
    ]
    snapshot = observe(data)
    assert snapshot["issues"][0]["validation_target"] == {"pr": 3, "head_sha": SHA}
    assert snapshot["autonomous_prs"][0]["ci_state"] == health.UNKNOWN


def test_ambiguous_pr_lineage_never_guesses_a_validation_target():
    data = evidence()
    add_issue(data, issue(1, ["oc-validating"]))
    data["pulls?state=open&base=oc-autonomous-integration&per_page=100&page=1"] = [
        {"number": n, "head": {"sha": SHA}, "body": "Fixes #1"} for n in (3, 4)
    ]
    receipt = health.build_health(observe(data))
    assert receipt["healthy"] is False
    assert receipt["observation_errors"][0]["reason"] == "ambiguous_validation_target"
    assert receipt["contract_health"]["violations"][0]["type"] == "validating_without_exact_head"


@pytest.mark.parametrize("jobs", [[], [{"runner_id": 0, "steps": [], "conclusion": "success"}]])
def test_success_without_executed_job_evidence_is_unknown(jobs):
    data = evidence()
    data["actions/runs/42/jobs?per_page=100&page=1"] = {"jobs": jobs}
    receipt = health.build_health(observe(data))
    assert receipt["healthy"] is False
    assert receipt["ci_infrastructure_state"]["state"] == health.UNKNOWN


def test_api_failure_is_not_an_empty_healthy_queue_and_error_text_is_redacted():
    def fail(endpoint):
        raise ValueError("secret=do-not-print raw API body")

    snapshot = health.collect_github_snapshot(REPO, 42, read_json=fail, now=NOW)
    receipt = health.build_health(snapshot)
    assert receipt["healthy"] is False
    assert receipt["observation_complete"] is False
    assert receipt["queued_p0_count"] == health.UNKNOWN
    assert "do-not-print" not in json.dumps(receipt)


def test_pagination_is_complete_or_explicitly_incomplete(monkeypatch):
    monkeypatch.setattr(health, "MAX_PAGES", 1)
    data = evidence()
    data["issues?state=open&per_page=100&page=1"] = [issue(n, []) for n in range(100)]
    receipt = health.build_health(observe(data))
    assert receipt["healthy"] is False
    assert {"source": "issues", "reason": "pagination_limit"} in receipt["observation_errors"]


def test_later_issue_pages_are_not_silently_lost():
    data = evidence()
    data["issues?state=open&per_page=100&page=1"] = [issue(n, []) for n in range(100)]
    data["issues?state=open&per_page=100&page=2"] = [issue(101, ["oc-running"])]
    data["issues/101"] = issue(101, ["oc-running"])
    data["issues/101/comments?per_page=100&page=1"] = []
    receipt = health.build_health(observe(data))
    assert receipt["contract_health"]["issues"]["running"] == [101]
    assert receipt["healthy"] is False


def test_read_budget_is_a_hard_bound(monkeypatch):
    monkeypatch.setattr(health, "MAX_READS", 2)
    calls = []

    def read(endpoint):
        calls.append(endpoint)
        return {"object": {"sha": SHA}}

    snapshot = health.collect_github_snapshot(REPO, 42, read_json=read, now=NOW)
    assert len(calls) == 2
    assert health.build_health(snapshot)["healthy"] is False


def test_issue_change_during_collection_fails_closed():
    data = evidence()
    add_issue(data, issue(1, ["oc-running"]), [claim(), started()])
    data["issues/1"] = {**data["issues/1"], "updated_at": "2026-09-12T03:31:00Z"}
    assert health.build_health(observe(data))["healthy"] is False


def test_integration_head_change_during_collection_fails_closed():
    data = evidence()
    calls = 0

    def read(endpoint):
        nonlocal calls
        if endpoint.endswith("git/ref/heads/oc-autonomous-integration"):
            calls += 1
            return {"object": {"sha": SHA if calls == 1 else "d" * 40}}
        return copy.deepcopy(data[endpoint.removeprefix(PREFIX)])

    receipt = health.build_health(health.collect_github_snapshot(REPO, 42, read_json=read, now=NOW))
    assert receipt["healthy"] is False
    assert receipt["observation_errors"][-1]["reason"] == "head_changed_during_observation"


@pytest.mark.parametrize("field,value", [("head_branch", "main"), ("path", ".github/workflows/unrelated.yml")])
def test_unrelated_successful_run_cannot_certify_the_scheduler(field, value):
    data = evidence()
    data["actions/runs/42"][field] = value
    receipt = health.build_health(observe(data))
    assert receipt["healthy"] is False
    assert {"source": "scheduler_run", "reason": "not_an_integration_controller_run"} in receipt["observation_errors"]


def test_pr_head_movement_during_observation_invalidates_the_receipt():
    data = evidence()
    path = "pulls?state=open&base=oc-autonomous-integration&per_page=100&page=1"
    data[path] = [{"number": 3, "head": {"sha": SHA}, "body": "Fixes #1"}]
    calls = 0

    def read(endpoint):
        nonlocal calls
        result = copy.deepcopy(data[endpoint.removeprefix(PREFIX)])
        if endpoint == PREFIX + path:
            calls += 1
            if calls == 2:
                result[0]["head"]["sha"] = "d" * 40
        return result

    receipt = health.build_health(health.collect_github_snapshot(REPO, 42, read_json=read, now=NOW))
    assert receipt["healthy"] is False
    assert {"source": "pull_requests", "reason": "inventory_changed_during_observation"} in receipt["observation_errors"]


@pytest.mark.parametrize("raw,code", [
    ({"issues": [], "leases": [], "dispatch_fingerprints": []}, 0),
    ({"issues": [{"number": 1, "labels": ["oc-running"]}], "leases": [], "dispatch_fingerprints": []}, 2),
    (None, 2),
    ({}, 2),
])
def test_cli_check_status_and_summary_are_the_actual_workflow_contract(tmp_path, raw, code):
    summary = tmp_path / "summary.md"
    result = subprocess.run(
        [sys.executable, "-m", "scripts.oc_control_plane_health", "--check", "--summary", str(summary)],
        input=json.dumps(raw), text=True, capture_output=True, cwd=ROOT, check=False,
    )
    assert result.returncode == code
    receipt = json.loads(result.stdout)
    assert receipt["healthy"] is (code == 0)
    assert ("INCONSISTENT OR INCOMPLETE" in summary.read_text()) is (code == 2)


def test_transport_is_get_only_without_shell_or_command_interpolation(monkeypatch):
    def run(argv, **kwargs):
        assert argv == ["gh", "api", "--method", "GET", PREFIX + "issues?state=open"]
        assert kwargs["timeout"] == 30
        assert kwargs.get("shell", False) is False
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    monkeypatch.setattr(subprocess, "run", run)
    assert health._github_get(PREFIX + "issues?state=open") == []


def test_workflow_observes_swarm_with_read_only_authority_and_persists_failed_receipts():
    path = ROOT / ".github/workflows/orchid-continuous-completion-observer.yml"
    workflow = yaml.safe_load(path.read_text())
    trigger = workflow.get("on", workflow.get(True))
    assert "Orchid Swarm Controller" in trigger["workflow_run"]["workflows"]
    assert trigger["workflow_run"]["branches"] == ["oc-autonomous-integration"]
    assert set(workflow["permissions"].values()) == {"read"}
    steps = workflow["jobs"]["report"]["steps"]
    checkout = steps[0]["with"]
    assert checkout["ref"] == "${{ github.sha }}"
    assert checkout["persist-credentials"] is False
    run = next(s["run"] for s in steps if "run" in s)
    assert "--check" in run
    assert "continue-on-error" not in path.read_text()
    assert subprocess.run(["bash", "-n"], input=run, text=True, capture_output=True, check=False).returncode == 0
    artifact = next(s for s in steps if "upload-artifact" in s.get("uses", ""))
    assert artifact["if"] == "always()"
