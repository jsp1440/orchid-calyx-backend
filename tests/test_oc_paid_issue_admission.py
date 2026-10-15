"""Paid provider admission is bound to an owner authorization on the issue.

Regression for the first governed window (#1823): with paid execution enabled
for one authorized issue, blocked reconciliation re-queued ten unauthorized
issues after a budget variable changed, and each one reached the provider.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
import yaml

from scripts import oc_hosted_completion as hosted
from scripts import oc_paid_issue_admission as admission

REPO = "jsp1440/orchid-calyx-backend"
NOW = datetime(2026, 10, 15, tzinfo=UTC)
WORKFLOW = ".github/workflows/orchid-completion-lane.yml"


def _issue():
    return {
        "number": 1843,
        "state": "open",
        "title": "Bottleneck report must not assert an unobserved next bottleneck",
        "body": "Allowed paths: runtime/bottlenecks.py\n",
        "labels": [{"name": "oc-queued"}],
    }


def _owner_record(target, /, **overrides):
    issue = target
    grant = {
        "repository": REPO,
        "issue": issue["number"],
        "issue_material": hosted.issue_material(issue),
        "target": hosted.BRANCH,
        "checker_calls": 1,
        "risk": "low",
        "allowed_paths": [
            "runtime/bottlenecks.py",
            "tests/test_runtime_bottlenecks.py",
        ],
        "expires_at": "2026-10-18T00:00:00Z",
    }
    grant.update(overrides)
    return {
        "id": 6183992365,
        "user": {"login": "jsp1440"},
        "author_association": "OWNER",
        "created_at": "2026-10-15T03:00:00Z",
        "updated_at": "2026-10-15T03:00:00Z",
        "body": hosted.tagged(hosted.AUTH_TAG, grant),
    }


def _decide(issue, comments):
    return admission.admit(
        REPO, issue["number"], fetch=lambda *_: (issue, comments), now=NOW
    )


def test_an_owner_authorized_issue_is_admitted():
    issue = _issue()
    decision = _decide(issue, [_owner_record(issue)])
    assert decision["authorized"] is True
    assert decision["authorization_comment"] == 6183992365


def test_an_issue_without_owner_authorization_is_refused():
    """The ten out-of-scope issues of the first window had no record at all."""
    decision = _decide(_issue(), [])
    assert decision == {
        "authorized": False,
        "reason": "OWNER_ISSUE_AUTHORIZATION_REQUIRED",
        "detail": "hosted_authorization_missing_or_ambiguous",
        "issue": 1843,
    }


def _edited(record):
    record["updated_at"] = "2026-10-15T04:00:00Z"


def _by_bot(record):
    record["user"] = {"login": "github-actions[bot]"}
    record["author_association"] = "NONE"


@pytest.mark.parametrize(
    ("mutate", "detail"),
    [
        (
            lambda issue, rec: issue.update(body="changed after approval"),
            "authorization_binding_invalid",
        ),
        (
            lambda issue, rec: rec.update(
                _owner_record(issue, expires_at="2026-10-14T00:00:00Z")
            ),
            "authorization_expired",
        ),
        (
            lambda issue, rec: rec.update(_owner_record(issue, risk="high")),
            "authorization_binding_invalid",
        ),
        (
            lambda issue, rec: rec.update(_owner_record(issue, issue=999)),
            "authorization_binding_invalid",
        ),
        (lambda issue, rec: _edited(rec), "authorization_edited"),
        (lambda issue, rec: _by_bot(rec), "authorization_not_owner"),
        (lambda issue, rec: issue.update(state="closed"), "issue_not_open"),
    ],
)
def test_every_invalid_or_stale_authorization_is_refused(mutate, detail):
    issue = _issue()
    record = _owner_record(issue)
    mutate(issue, record)
    decision = _decide(issue, [record])
    assert decision["authorized"] is False
    assert decision["reason"] == "OWNER_ISSUE_AUTHORIZATION_REQUIRED"
    assert decision["detail"] == detail


def test_two_records_are_ambiguous_and_refused():
    issue = _issue()
    record = _owner_record(issue)
    decision = _decide(issue, [record, copy.deepcopy(record)])
    assert decision["authorized"] is False


def test_a_read_failure_fails_closed():
    def broken(*_):
        raise OSError("api unavailable")

    decision = admission.admit(REPO, 1843, fetch=broken, now=NOW)
    assert decision["authorized"] is False
    assert decision["reason"] == "OWNER_ISSUE_AUTHORIZATION_REQUIRED"


def test_the_denial_reason_is_in_the_governor_vocabulary():
    from scripts.oc_budget_denial_route import DENIAL_REASON

    assert DENIAL_REASON.fullmatch(admission.DENIAL)


def _steps():
    with open(WORKFLOW, encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)
    (job,) = workflow["jobs"].values()
    return job["steps"]


def test_no_provider_step_can_run_without_issue_admission():
    steps = _steps()
    ids = [step.get("id") for step in steps]
    auth, governor = ids.index("issue_auth"), ids.index("governor")
    assert auth < governor
    assert "steps.issue_auth.outputs.authorized == 'true'" in steps[governor]["if"]
    assert steps[auth].get("continue-on-error") is True
    for step in steps:
        run = str(step.get("run") or "")
        if "swarm_anthropic_direct.py" in run:
            assert "steps.governor.outputs.authorized == 'true'" in step["if"]


def test_an_admission_refusal_is_parked_through_the_governor_denial_path():
    steps = _steps()
    (denial,) = [s for s in steps if "--park-denied" in str(s.get("run") or "")]
    assert "steps.governor.outputs.authorized != 'true'" in denial["if"]
    reason = denial["env"]["DENIAL_REASON"]
    assert "steps.issue_auth.outputs.authorized != 'true'" in reason
    assert "OWNER_ISSUE_AUTHORIZATION_REQUIRED" in reason


def test_paid_coding_work_is_planned_only_on_the_integration_ref():
    """A PR-close run (#1847) leased #1843 and started a paid worker on the PR
    branch; hosted completion can only accept workers on the integration ref."""
    with open(
        ".github/workflows/orchid-swarm-controller.yml", encoding="utf-8"
    ) as handle:
        text = handle.read()
    start = text.index("provider_args=()")
    gate = text[start : text.index("provider_args+=(--coding-executor)", start)]
    assert 'steps.coding_governor.outputs.authorized }}" == "true"' in gate
    assert (
        'steps.controller_revision.outputs.canonical_integration }}" == "true"' in gate
    )
    assert '"${{ github.event_name }}" == "schedule"' in gate
    assert '"${{ github.ref }}" == "refs/heads/oc-autonomous-integration"' in gate


@pytest.mark.parametrize(
    ("run", "trusted"),
    [
        (
            {"head_branch": "oc-autonomous-integration", "event": "workflow_dispatch"},
            True,
        ),
        ({"head_branch": "main", "event": "schedule"}, True),
        ({"head_branch": "main", "event": "pull_request"}, False),
        ({"head_branch": "main", "event": "issues"}, False),
        ({"head_branch": "main", "event": "workflow_dispatch"}, False),
        ({"head_branch": "feature", "event": "schedule"}, False),
        # A PR (even from a branch named like the integration ref) is never a worker.
        ({"head_branch": "oc-autonomous-integration", "event": "pull_request"}, False),
        (
            {
                "head_branch": "oc-autonomous-integration",
                "event": "workflow_dispatch",
                "head_repository": {"full_name": "fork/orchid-calyx-backend"},
            },
            False,
        ),
    ],
)
def test_one_trust_rule_for_controller_runs(run, trusted):
    from scripts.oc_controller_trust import on_trusted_controller_ref

    assert on_trusted_controller_ref(run, "main", repository=REPO) is trusted
    if run.get("event") == "schedule":
        assert on_trusted_controller_ref(run, "", repository=REPO) is False


def test_checker_job_can_write_pr_receipts_but_its_provider_step_gets_no_token():
    with open(
        ".github/workflows/oc-convergence-supervisor.yml", encoding="utf-8"
    ) as handle:
        workflow = yaml.safe_load(handle)
    checker = workflow["jobs"]["checker"]
    assert checker["permissions"]["pull-requests"] == "write"
    (provider,) = [
        s
        for s in checker["steps"]
        if s.get("name") == "Independent read-only checker session"
    ]
    assert set(provider["env"]) == {"ANTHROPIC_API_KEY"}
