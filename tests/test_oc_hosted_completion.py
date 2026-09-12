"""Independent contracts for the privileged hosted completion boundary."""

from __future__ import annotations

import base64
import copy
import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.calyx_orchestrator.checker_dispatch import (
    CheckerEvidence,
    assign_checker,
    serialize_assignment,
    serialize_evidence,
)
from app.calyx_orchestrator.factory_policy import CheckerVerdict, RiskTier, WorkIntent
from runtime.swarm.work_packet import build_work_packet
from scripts import oc_hosted_completion as hosted

REPO = "jsp1440/orchid-calyx-backend"
HEAD = "a" * 40
TRUSTED = "b" * 40
BASE = "c" * 40
MERGE = "d" * 40
NOW = datetime(2026, 9, 12, tzinfo=timezone.utc)
PATHS = ["scripts/oc_control_plane_health.py", "tests/test_oc_control_plane_health.py"]


@pytest.fixture
def material():
    context = {
        "repository": REPO,
        "issue": 1400,
        "pr": 1401,
        "head": HEAD,
        "trusted_sha": TRUSTED,
        "worker_run": 1000,
        "worker_attempt": 1,
        "completion_run": 1001,
        "lease": 2000,
    }
    issue = {
        "number": 1400,
        "title": "Expose incomplete observations accurately",
        "body": "Improve read-only observer diagnostics.\nOC-SWARM-WRITES: control-plane",
        "state": "open",
        "labels": [{"name": "oc-validating"}, {"name": "oc-p4"}],
    }
    grant = {
        "repository": REPO,
        "issue": 1400,
        "issue_material": hosted.issue_material(issue),
        "target": hosted.BRANCH,
        "checker_calls": 1,
        "risk": "low",
        "allowed_paths": PATHS,
        "expires_at": "2099-01-01T00:00:00Z",
    }
    owner = {
        "id": 2001,
        "user": {"login": "jsp1440"},
        "author_association": "OWNER",
        "created_at": "2026-09-12T00:00:00Z",
        "updated_at": "2026-09-12T00:00:00Z",
        "body": hosted.tagged(hosted.AUTH_TAG, grant),
    }
    grant = hosted.authorization(issue, [owner], REPO, NOW)
    pr = {
        "number": 1401,
        "state": "open",
        "head": {
            "sha": HEAD,
            "ref": "claude-direct/issue-1400-1000",
            "repo": {"full_name": REPO},
        },
        "base": {"ref": hosted.BRANCH, "repo": {"full_name": REPO}},
        "user": {"login": "github-actions[bot]"},
        "body": "OC-AUTO-ISSUE: #1400\n",
        "draft": False,
    }
    packet = build_work_packet(
        issue_number="1400",
        title=issue["title"],
        body=issue["body"],
        labels={"oc-running", "oc-p4"},
    )
    claim = {
        "schema": "oc.swarm-claim.v1",
        "issue_number": 1400,
        "lease_id": f"{REPO}:1000:1:1400",
        "material_fingerprint": packet.fingerprint,
        "dependencies": [],
        "reads": [],
        "writes": ["control-plane"],
    }
    lease = {
        "id": 2000,
        "user": {"login": "github-actions[bot]"},
        "issue_url": f"https://api.github.com/repos/{REPO}/issues/1400",
        "body": f"[OC-SWARM-V4] Dependency/resource lease claimed: `{json.dumps(claim)}`.",
    }
    files = [
        {
            "filename": path,
            "status": "modified",
            "patch": "@@ -1 +1 @@\n-old\n+new",
            "additions": 1,
            "deletions": 1,
        }
        for path in PATHS
    ]
    return {
        "context": context,
        "issue": issue,
        "pr": pr,
        "lease": lease,
        "grant": grant,
        "owner": owner,
        "files": files,
    }


def authorize(material, **overrides):
    record = copy.deepcopy(material["owner"])
    grant = hosted.parse_tag(record["body"], hosted.AUTH_TAG)
    grant.update(overrides)
    record["body"] = hosted.tagged(hosted.AUTH_TAG, grant)
    return hosted.authorization(material["issue"], [record], REPO, NOW)


def validate(material):
    return hosted.validate_material(
        material["context"],
        material["issue"],
        material["pr"],
        material["lease"],
        material["files"],
        material["grant"],
        material.get("dependencies", []),
    )


def review(**overrides):
    result = {
        "verdict": "pass",
        "reason": "The changed regression covers missing evidence.",
        "risk": "low",
        "reversible": True,
        **{field: False for field in hosted.RISK_FIELDS},
    }
    result.update(overrides)
    return result


def response(value):
    return {
        "stop_reason": "end_turn",
        "content": [{"type": "text", "text": json.dumps(value)}],
    }


def factory_state(material, **review_changes):
    context = material["context"]
    intent = WorkIntent(
        REPO,
        context["issue"],
        HEAD,
        hosted.BRANCH,
        risk_tier=RiskTier(material["grant"]["risk"]),
    )
    assignment = assign_checker(intent, context["pr"], "maker:1000", ["checker:1001"])
    assessment = review(**review_changes)
    evidence = CheckerEvidence(
        REPO,
        context["issue"],
        context["pr"],
        HEAD,
        assignment.checker_id,
        assignment.maker_id,
        CheckerVerdict(assessment["verdict"]),
        True,
        assessment["reason"],
        assignment.material_fingerprint,
    )
    validation = {"run": {"id": 3000, "run_attempt": 1}, "base_sha": BASE}
    state = {
        "context": context,
        "grant": material["grant"],
        "intent": asdict(intent),
        "assignment": asdict(assignment),
        "assignment_comment": 3001,
        "evidence_comment": 3002,
        "evidence_body": serialize_evidence(evidence),
        "review": assessment,
        "validation": validation,
    }
    return state, validation, assignment, evidence


def test_scoped_owner_authorization_and_real_claim_material_pass(material):
    assert material["grant"]["comment_id"] == material["owner"]["id"]
    before = copy.deepcopy(material)
    assert validate(material)["passed"] is True
    assert material == before


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository": "other/repo"},
        {"issue": 999},
        {"issue_material": "wrong"},
        {"target": "main"},
        {"checker_calls": 2},
        {"checker_calls": True},
        {"risk": "high"},
        {"expires_at": "2026-09-11T00:00:00Z"},
    ],
)
def test_invalid_authorization_never_admits_work(material, overrides):
    with pytest.raises(ValueError):
        authorize(material, **overrides)


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/worker.yml",
        "AGENTS.md",
        "CLAUDE.md",
        "requirements.txt",
        "scripts/oc_hosted_completion.py",
        "scripts/agent_security_guard.py",
        "scripts/swarm_anthropic_direct.py",
        "app/calyx_orchestrator/checker_dispatch.py",
        "app/calyx_orchestrator/factory_policy.py",
        "runtime/swarm/policy.py",
        "migrations/999.sql",
        "../outside.py",
        "/tmp/outside.py",
    ],
)
def test_owner_enrollment_cannot_weaken_protected_path_boundary(material, path):
    with pytest.raises(ValueError, match="unsafe_allowed_paths"):
        authorize(material, allowed_paths=[path])


def test_owner_record_must_be_unique_and_authentic(material):
    owner = material["owner"]
    for records in ([], [owner, owner]):
        with pytest.raises(ValueError, match="missing_or_ambiguous"):
            hosted.authorization(material["issue"], records, REPO, NOW)
    owner["user"]["login"] = "github-actions[bot]"
    with pytest.raises(ValueError, match="authorization_not_owner"):
        hosted.authorization(material["issue"], [owner], REPO, NOW)


def test_edited_owner_record_is_not_immutable_authority(material):
    material["owner"]["updated_at"] = "2026-09-12T00:01:00Z"
    with pytest.raises(ValueError):
        hosted.authorization(material["issue"], [material["owner"]], REPO, NOW)


@pytest.mark.parametrize(
    "label",
    ["oc-running", "oc-queued", "oc-done", "oc-owner-gate", "oc-repair-backoff"],
)
def test_contradictory_queue_labels_block_completion(material, label):
    material["issue"]["labels"].append({"name": label})
    with pytest.raises(ValueError, match="exclusively_validating"):
        validate(material)


@pytest.mark.parametrize(
    "change",
    [
        "head",
        "base",
        "fork",
        "maker",
        "hold",
        "marker",
        "lease",
        "fingerprint",
        "scope",
        "deleted",
        "missing_patch",
        "no_test",
    ],
)
def test_changed_material_is_rejected_before_any_action(material, change):
    if change == "head":
        material["pr"]["head"]["sha"] = "e" * 40
    elif change == "base":
        material["pr"]["base"]["ref"] = "main"
    elif change == "fork":
        material["pr"]["head"]["repo"]["full_name"] = "fork/repo"
    elif change == "maker":
        material["pr"]["user"]["login"] = "untrusted-maker"
    elif change == "hold":
        material["pr"]["body"] += "OC-AUTO-HOLD: true\n"
    elif change == "marker":
        material["pr"]["body"] += "OC-AUTO-ISSUE: #1400\n"
    elif change == "lease":
        material["context"]["worker_attempt"] = 2
    elif change == "fingerprint":
        material["issue"]["labels"].append({"name": "oc-p1"})
    elif change == "scope":
        material["files"][0]["filename"] = "app/other.py"
    elif change == "deleted":
        material["files"][0]["status"] = "removed"
    elif change == "missing_patch":
        material["files"][0].pop("patch")
    elif change == "no_test":
        material["files"].pop()
    with pytest.raises(ValueError):
        validate(material)


def test_reopened_dependency_cannot_be_bypassed(material):
    material["issue"]["body"] += "\nOC-SWARM-DEPENDS-ON: #1399"
    material["grant"]["issue_material"] = hosted.issue_material(material["issue"])
    packet = build_work_packet(
        issue_number="1400",
        title=material["issue"]["title"],
        body=material["issue"]["body"],
        labels={"oc-running", "oc-p4"},
    )
    claim = json.loads(material["lease"]["body"].split("`")[1])
    claim.update(dependencies=[1399], material_fingerprint=packet.fingerprint)
    material["lease"]["body"] = (
        f"[OC-SWARM-V4] Dependency/resource lease claimed: `{json.dumps(claim)}`."
    )
    material["dependencies"] = [
        {
            "number": 1399,
            "title": "Prerequisite",
            "body": "",
            "state": "open",
            "labels": [],
        }
    ]
    with pytest.raises(ValueError, match="dependency_not_satisfied"):
        validate(material)


@pytest.mark.parametrize("field", ["additions", "deletions"])
def test_server_truncated_diff_never_reaches_checker(material, field):
    material["files"][0][field] += 1
    with pytest.raises(ValueError, match="diff_truncated"):
        validate(material)


def test_checker_accepts_only_completed_strict_structured_review():
    assert hosted.parse_review(response(review())) == review()


@pytest.mark.parametrize("field", [*hosted.RISK_FIELDS, "reversible"])
@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], {}])
def test_checker_never_coerces_risk_flags(field, value):
    with pytest.raises(ValueError, match="checker_fields_invalid"):
        hosted.parse_review(response(review(**{field: value})))


@pytest.mark.parametrize(
    "change",
    ["truncated", "tool", "extra", "missing", "unknown_verdict", "unknown_risk"],
)
def test_ambiguous_checker_result_stays_closed(change):
    value = response(review())
    if change == "truncated":
        value["stop_reason"] = "max_tokens"
    elif change == "tool":
        value["content"][0]["type"] = "tool_use"
    elif change == "extra":
        value = response(review(extra_authority=True))
    elif change == "missing":
        assessment = review()
        assessment.pop("changes_credentials")
        value = response(assessment)
    elif change == "unknown_verdict":
        value = response(review(verdict="approved"))
    elif change == "unknown_risk":
        value = response(review(risk="safe"))
    with pytest.raises(ValueError):
        hosted.parse_review(value)


def test_existing_factory_admits_independent_exact_head_pass(material):
    state, checked, assignment, evidence = factory_state(material)
    decision = hosted.decide(state, material, checked, assignment, evidence)
    assert decision.action.value == "auto_integrate"
    assert decision.integration_authorized is True


@pytest.mark.parametrize("field", hosted.RISK_FIELDS)
def test_checker_owner_boundary_always_prevents_auto_integration(material, field):
    state, checked, assignment, evidence = factory_state(material, **{field: True})
    decision = hosted.decide(state, material, checked, assignment, evidence)
    assert decision.action.value == "owner_gate"
    assert decision.integration_authorized is False


@pytest.mark.parametrize(
    "changes,action",
    [
        ({"risk": "high"}, "owner_gate"),
        ({"reversible": False}, "owner_gate"),
        ({"verdict": "fail"}, "prepare_repair"),
        ({"verdict": "inconclusive"}, "require_checker"),
    ],
)
def test_nonpass_or_unsafe_review_never_merges(material, changes, action):
    state, checked, assignment, evidence = factory_state(material, **changes)
    decision = hosted.decide(state, material, checked, assignment, evidence)
    assert decision.action.value == action
    assert decision.integration_authorized is False


@pytest.mark.parametrize(
    "change", ["grant", "base", "run", "attempt", "assignment", "evidence"]
)
def test_factory_rejects_changed_durable_material(material, change):
    state, checked, assignment, evidence = factory_state(material)
    current = copy.deepcopy(checked)
    current_material = copy.deepcopy(material)
    if change == "grant":
        current_material["grant"]["digest"] = "different"
    elif change == "base":
        current["base_sha"] = "e" * 40
    elif change == "run":
        current["run"]["id"] += 1
    elif change == "attempt":
        current["run"]["run_attempt"] += 1
    elif change == "assignment":
        assignment = replace(assignment, checker_id="another-checker")
    else:
        evidence = replace(evidence, checked_head_sha="e" * 40)
    with pytest.raises(ValueError):
        hosted.decide(state, current_material, current, assignment, evidence)


def test_owner_risk_cannot_be_lowered_by_checker(material):
    material["grant"]["risk"] = "moderate"
    state, checked, assignment, evidence = factory_state(material, risk="low")
    decision = hosted.decide(state, material, checked, assignment, evidence)
    assert decision.factory.fingerprint == assignment.material_fingerprint


def settlement_harness(monkeypatch, tmp_path, material, failure=None, **assessment):
    state, checked, assignment, evidence = factory_state(material, **assessment)
    (tmp_path / "prepared.json").write_text(json.dumps(state))
    monkeypatch.setattr(hosted, "inspect", lambda context: copy.deepcopy(material))
    monkeypatch.setattr(
        hosted, "validation", lambda context, current: copy.deepcopy(checked)
    )
    receipts = {}
    for number, body in (
        (3001, serialize_assignment(assignment)),
        (3002, serialize_evidence(evidence)),
    ):
        receipts[number] = {
            "id": number,
            "body": body,
            "user": {"login": "github-actions[bot]"},
            "issue_url": f"https://api.github.com/repos/{REPO}/issues/1401",
        }
    if failure == "forged_evidence":
        receipts[3002]["body"] = receipts[3002]["body"].replace(
            '"required_checks_passed": true', '"required_checks_passed": "false"'
        )
    issue = copy.deepcopy(material["issue"])
    calls = []

    def fake_api(repository, path, payload=None, method="GET"):
        assert repository == REPO
        calls.append((method, path, copy.deepcopy(payload)))
        if path.startswith("issues/comments/"):
            return copy.deepcopy(receipts[int(path.rsplit("/", 1)[1])])
        if path.endswith("/comments") and method == "POST":
            number = max(receipts) + 1
            body = payload["body"]
            if (
                failure == "decision_receipt"
                and "OC-HOSTED-FACTORY-DECISION-V1" in body
            ):
                body = "contradictory server response"
            if failure == "merge_receipt" and "OC-HOSTED-MERGE-VERIFIED-V1" in body:
                body = "contradictory server response"
            receipts[number] = {
                "id": number,
                "body": body,
                "user": {"login": "github-actions[bot]"},
                "issue_url": f"https://api.github.com/repos/{REPO}/{path.removesuffix('/comments')}",
            }
            return copy.deepcopy(receipts[number])
        if path == "pulls/1401/merge" and method == "PUT":
            assert payload == {"sha": HEAD, "merge_method": "merge"}
            return {"merged": failure != "merge_rejected", "sha": MERGE}
        if path == "pulls/1401":
            result = copy.deepcopy(material["pr"])
            result.update(merged=True, merge_commit_sha=MERGE)
            if failure == "merge_head":
                result["head"]["sha"] = "e" * 40
            return result
        if path == f"git/commits/{MERGE}":
            return {
                "parents": [
                    {"sha": "e" * 40 if failure == "merge_parents" else BASE},
                    {"sha": HEAD},
                ]
            }
        if path == "issues/1400":
            if method == "PATCH" and failure != "settlement_rejected":
                issue.update({k: v for k, v in payload.items() if k != "labels"})
                issue["labels"] = [{"name": label} for label in payload["labels"]]
            return copy.deepcopy(issue)
        raise AssertionError(f"Unexpected API operation: {method} {path}")

    monkeypatch.setattr(hosted, "api", fake_api)
    return calls, issue, receipts


def test_settlement_requires_real_merge_then_receipt_then_exact_final_state(
    monkeypatch, tmp_path, material
):
    calls, issue, receipts = settlement_harness(monkeypatch, tmp_path, material)
    hosted.settle(tmp_path)
    assert issue["state"] == "closed"
    assert {label["name"] for label in issue["labels"]} == {"oc-done", "oc-p4"}
    merged_at = next(
        i for i, c in enumerate(calls) if c[:2] == ("PUT", "pulls/1401/merge")
    )
    done_at = next(i for i, c in enumerate(calls) if c[:2] == ("PATCH", "issues/1400"))
    receipt_at = next(
        i
        for i, c in enumerate(calls)
        if c[0] == "POST" and "OC-HOSTED-MERGE-VERIFIED-V1" in c[2]["body"]
    )
    assert merged_at < receipt_at < done_at
    saved = json.loads((tmp_path / "settlement.json").read_text())
    assert saved["merge_sha"] == MERGE
    assert "OC-HOSTED-SETTLEMENT-V1" in receipts[saved["settlement_receipt"]]["body"]


@pytest.mark.parametrize(
    "failure",
    [
        "decision_receipt",
        "forged_evidence",
        "merge_rejected",
        "merge_head",
        "merge_parents",
        "merge_receipt",
    ],
)
def test_unconfirmed_or_forged_evidence_never_marks_done(
    monkeypatch, tmp_path, material, failure
):
    calls, issue, _ = settlement_harness(monkeypatch, tmp_path, material, failure)
    with pytest.raises(ValueError):
        hosted.settle(tmp_path)
    assert issue["state"] == "open"
    assert not any(
        method == "PATCH" and "oc-done" in payload.get("labels", [])
        for method, _, payload in calls
    )
    if failure in {"decision_receipt", "forged_evidence"}:
        assert not any(method == "PUT" for method, _, _ in calls)


@pytest.mark.parametrize(
    "verdict,label", [("fail", "oc-repair"), ("inconclusive", "oc-validating")]
)
def test_checker_nonpass_routes_without_merge_or_requeue(
    monkeypatch, tmp_path, material, verdict, label
):
    calls, issue, _ = settlement_harness(
        monkeypatch, tmp_path, material, verdict=verdict
    )
    with pytest.raises(ValueError, match="factory_did_not_authorize"):
        hosted.settle(tmp_path)
    assert {x["name"] for x in issue["labels"]} & hosted.STATE_LABELS == {label}
    assert not any(method == "PUT" for method, _, _ in calls)


def test_truncated_api_inventory_is_never_accepted(monkeypatch):
    monkeypatch.setattr(hosted, "api", lambda *args: [{}] * 100)
    with pytest.raises(ValueError, match="inventory_truncated"):
        hosted.pages(REPO, "issues")


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "skipped_step",
        "runner_zero",
        "failed_run",
        "stale_run",
        "missing_check",
        "pending_check",
    ],
)
def test_hosted_validation_requires_actual_exact_head_execution(
    monkeypatch, material, failure
):
    material["worker"] = {"created_at": "2026-09-12T00:00:00Z"}
    run = {
        "id": 3000,
        "head_sha": HEAD,
        "head_branch": material["pr"]["head"]["ref"],
        "event": "workflow_dispatch",
        "created_at": "2026-09-12T00:01:00Z",
        "path": ".github/workflows/orchid-autonomous-validation.yml",
        "actor": {"login": "github-actions[bot]"},
        "status": "completed",
        "conclusion": "success",
    }
    job = {
        "runner_id": 42,
        "conclusion": "success",
        "steps": [
            {"name": name, "conclusion": "success"}
            for name in (
                "Swarm post-build write-set verification",
                "Compile Python sources",
                "Validate changed Python files",
                "Diff hygiene",
            )
        ],
    }
    checks = [{"name": "validate", "status": "completed", "conclusion": "success"}]
    if failure == "skipped_step":
        job["steps"][0]["conclusion"] = "skipped"
    elif failure == "runner_zero":
        job["runner_id"] = 0
    elif failure == "failed_run":
        run["conclusion"] = "failure"
    elif failure == "stale_run":
        run["head_sha"] = BASE
    elif failure == "missing_check":
        checks.clear()
    elif failure == "pending_check":
        checks[0]["status"] = "in_progress"

    def fake_pages(repo, path, field=None):
        if "workflows/" in path:
            return [run]
        if path.endswith("/jobs"):
            return [job]
        if path.endswith("/check-runs"):
            return checks
        raise AssertionError(path)

    def fake_api(repo, path):
        if path.endswith("/status"):
            return {"total_count": 0}
        if path == f"branches/{hosted.BRANCH}":
            return {"protected": False, "commit": {"sha": BASE}}
        raise AssertionError(path)

    monkeypatch.setattr(hosted, "pages", fake_pages)
    monkeypatch.setattr(hosted, "api", fake_api)
    if failure:
        with pytest.raises(ValueError):
            hosted.validation(material["context"], material)
    else:
        assert hosted.validation(material["context"], material)["run"]["id"] == 3000


def test_reserved_attempt_cannot_be_replayed_or_spent_again(
    monkeypatch, tmp_path, material
):
    state, _, _, _ = factory_state(material)
    (tmp_path / "prepared.json").write_text(json.dumps(state))
    material["comments"] = [{"body": hosted.tagged(hosted.ATTEMPT_TAG, {"run": 1001})}]
    monkeypatch.setattr(hosted, "inspect", lambda context: material)
    monkeypatch.setattr(
        hosted, "comment", lambda *args: pytest.fail("Replay wrote an attempt")
    )
    with pytest.raises(ValueError, match="checker_attempt_already_reserved"):
        hosted.reserve(tmp_path)


def test_checker_cannot_initialize_provider_without_reservation(
    monkeypatch, tmp_path, material
):
    state, _, _, _ = factory_state(material)
    (tmp_path / "prepared.json").write_text(json.dumps(state))
    monkeypatch.setattr(
        hosted.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("Unreserved provider call"),
    )
    with pytest.raises(ValueError, match="checker_reservation_missing"):
        hosted.check(tmp_path)


def test_observer_persists_existing_violations_before_holding_continuation(
    monkeypatch, tmp_path, material
):
    snapshot = {
        "issues": [{"number": 1360, "labels": ["oc-running"]}],
        "leases": [],
        "dispatch_fingerprints": [],
    }
    monkeypatch.setattr(hosted, "context_from_env", lambda: material["context"])
    monkeypatch.setattr(
        hosted, "collect_github_snapshot", lambda *args, **kwargs: snapshot
    )
    saved = {}
    comments = []

    def fake_api(repo, path, payload=None, method="GET"):
        assert path.startswith("contents/docs/brain/evidence/OC-HOSTED-1400-1001.json")
        if method == "PUT":
            assert payload["branch"] == hosted.BRANCH
            assert (
                "sha" not in payload
            )  # Create only, never overwrite an existing receipt.
            saved.update(payload)
            return {"content": {"sha": "e" * 40}}
        return {"sha": "e" * 40, "content": saved["content"]}

    monkeypatch.setattr(hosted, "api", fake_api)
    monkeypatch.setattr(
        hosted, "comment", lambda repo, issue, body: comments.append(body)
    )
    with pytest.raises(ValueError, match="health_contract_not_green"):
        hosted.observe(tmp_path)
    durable = json.loads(base64.b64decode(saved["content"]))
    violations = durable["health"]["contract_health"]["violations"]
    assert any(v["type"] == "running_lease_cardinality" for v in violations)
    assert durable["health"]["healthy"] is False
    assert durable["central_brain_sync"].startswith("UNPROVEN")
    assert "running_lease_cardinality" in comments[0]
    assert (
        json.loads((tmp_path / "health.json").read_text())["contract_health"][
            "violations"
        ]
        == violations
    )


def test_hosted_workflow_isolates_candidate_data_and_spending_credentials():
    import yaml

    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load(
        (root / ".github/workflows/oc-convergence-supervisor.yml").read_text()
    )
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"workflow_dispatch"}
    assert (
        workflow["concurrency"]["group"]
        == "swarm-paid-execution-${{ github.repository }}"
    )
    assert workflow["concurrency"]["cancel-in-progress"] is False
    checker = workflow["jobs"]["checker"]
    assert "vars.NO_API_MODE == 'false'" in checker["if"]
    assert checker["permissions"]["contents"] == "read"
    assert checker["permissions"]["pull-requests"] == "read"
    steps = checker["steps"]
    provider = next(
        i
        for i, step in enumerate(steps)
        if step.get("name") == "Independent read-only checker session"
    )
    reserve = next(
        i
        for i, step in enumerate(steps)
        if "Reserve one durable" in step.get("name", "")
    )
    governor = next(i for i, step in enumerate(steps) if step.get("id") == "governor")
    assert governor < reserve < provider
    assert steps[provider]["if"] == "steps.governor.outputs.authorized == 'true'"
    assert set(steps[provider]["env"]) == {"ANTHROPIC_API_KEY"}
    assert "GH_TOKEN" not in workflow.get("env", {})
    assert "GH_TOKEN" not in checker.get("env", {})
    for name in ("checker", "factory", "observation"):
        job = workflow["jobs"][name]
        checkout = next(
            step
            for step in job["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        )
        assert checkout["with"]["ref"] == "${{ github.sha }}"
        assert checkout["with"]["persist-credentials"] is False
    continuation = workflow["jobs"]["continuation"]["if"]
    assert "vars.OC_GOVERNOR_AUTO_REFILL == 'true'" in continuation
    assert "needs.factory.result == 'success'" in continuation
    assert "needs.observation.result == 'success'" in continuation
