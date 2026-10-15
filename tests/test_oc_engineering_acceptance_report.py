"""acceptance-report.json: only real, independently validated, receipted cycles count.

Every fixture mirrors the record its producer writes:

* claim -- ``oc_swarm_claim`` (``lease_id = repo:run:attempt:issue``);
* worker receipt -- ``orchid-completion-lane`` (``Run …/actions/runs/<run>``);
* maker PR -- ``swarm_anthropic_direct`` (bot, ``claude-direct/issue-<n>-<run>``,
  ``OC-AUTO-ISSUE: #<n>``);
* validation run -- what ``oc_hosted_completion.validation`` accepts;
* checker record -- ``serialize_evidence`` with the ids ``oc_hosted_completion``
  assigns (``anthropic:maker:<worker_run>:<n>``, ``anthropic:checker:<run>:<n>``);
* settlement -- ``OC-HOSTED-SETTLEMENT-V1``;
* recovery -- ``oc_swarm_lease_reconcile.apply_recovery`` (no ``action``, with
  ``released_state``).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from app.calyx_orchestrator.checker_dispatch import CheckerEvidence, serialize_evidence
from app.calyx_orchestrator.factory_policy import CheckerVerdict

REPO = "jsp1440/orchid-calyx-backend"
ROOT = Path(__file__).resolve().parents[1]
BOT = {"login": "github-actions[bot]"}
OWNER = {"login": "jsp1440"}
BASE = "e" * 40


def _module():
    spec = importlib.util.spec_from_file_location(
        "oc_engineering_acceptance_report",
        ROOT / "scripts" / "oc_engineering_acceptance_report.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(n, salt):
    return f"{salt}{n:039x}"[-40:]


def _day(n):
    return f"2026-10-{16 + n // 24:02d}T{n % 24:02d}"


def _c(cid, body, at, user=BOT):
    return {
        "id": cid,
        "body": body,
        "created_at": at,
        "user": user,
        "html_url": f"https://github.com/{REPO}/c/{cid}",
    }


def _claim(cid, issue_no, run, attempt, at):
    claim = {
        "issue_number": issue_no,
        "lease_id": f"{REPO}:{run}:{attempt}:{issue_no}",
        "schema": "oc.swarm-claim.v1",
        "dependencies": [],
        "reads": [],
        "writes": [],
        "material_fingerprint": "f" * 16,
    }
    return _c(
        cid,
        "[OC-SWARM-V4] Dependency/resource lease claimed: `"
        + json.dumps(claim, separators=(",", ":"))
        + "`.",
        at,
    )


def _recovery_comment(issue_no, controller_run, old_run, at, cid=10, **kw):
    receipt = {
        "schema": "oc.swarm-lease-recovery.v1",
        "issue_number": issue_no,
        "reason": kw.get("reason", "worker_run_terminated_without_settlement"),
        "target": "oc-queued",
        "lease_id": kw.get("lease", f"{REPO}:{old_run}:1:{issue_no}"),
        "lease_comment_id": kw.get("comment", 8),
        "run_id": kw.get("lease_run", old_run),
        "run_status": "cancelled",
        "lease_age_seconds": 900,
        "recoveries_before": 0,
        "durable_pr": None,
        "labels": ["oc-running"],
        "released_state": kw.get("released", ["oc-queued"]),
    }
    receipt.update(kw.get("extra", {}))
    return _c(
        cid,
        "[OC-SWARM-V4] Stale lease recovered: `"
        + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        + f"`. Controller run: https://github.com/{REPO}/actions/runs/{controller_run}.",
        at,
        user=kw.get("user", BOT),
    )


def _vrun(n, head, branch, **over):
    row = {
        "id": int(f"8{n:03d}"),
        "head_sha": head,
        "head_branch": branch,
        "event": "workflow_dispatch",
        "actor": BOT,
        "path": ".github/workflows/orchid-autonomous-validation.yml",
        "conclusion": "success",
        "created_at": f"{_day(n)}:10:00Z",
        "html_url": f"https://github.com/{REPO}/actions/runs/8{n:03d}",
    }
    row.update(over)
    return row


def _record(n, **kw):
    issue_no, pr_no = 2000 + n, 3000 + n
    run, attempt = int(f"9{n:03d}"), 1
    head, merge = _sha(n, "a"), _sha(n, "b")
    day = _day(n)
    branch = kw.get("pr_branch", f"claude-direct/issue-{issue_no}-{run}")
    comments = []
    if kw.get("recovered"):
        old_run = int(f"7{n:03d}")
        comments.append(_claim(8, issue_no, old_run, 1, f"{day}:00:00Z"))
        comments.append(
            _recovery_comment(
                issue_no,
                run,
                old_run,
                kw.get("recovery_at", f"{day}:00:40Z"),
                **kw.get("recovery", {}),
            )
        )
    comments.append(_claim(11, issue_no, run, attempt, f"{day}:01:00Z"))
    comments.append(
        _c(
            12,
            "[OC-AUTO] Completion worker started from workflow_dispatch; economy-policy=one-provider-per-run; "
            "primary=Claude; route=tier=cheap; model=claude-haiku-4-5; reason=explicit-label=oc-model-cheap; "
            f"packet=ffff. Run https://github.com/{REPO}/actions/runs/{kw.get('worker_receipt_run', run)}.",
            f"{day}:01:10Z",
        )
    )
    if n == 2:
        comments.append(
            _c(
                9,
                "[OC-SWARM-V4] Worker result validated; requested lease disposition: `"
                + json.dumps(
                    {
                        "disposition": "repair",
                        "message": "Bounded ceiling (max_turns).",
                        "x": {"a": 1},
                    }
                )
                + "`.",
                f"{day}:00:30Z",
            )
        )
    if kw.get("unexplained_zero"):
        comments.append(
            _c(
                13,
                "[OC-SWARM-V4] Worker result validated; requested lease disposition: `"
                + json.dumps({"disposition": "runtime-backoff"})
                + "`.",
                f"{day}:00:31Z",
            )
        )
    if kw.get("denied"):
        comments.append(
            _c(
                14,
                "[OC-SWARM-V4] Provider admission denied; requested lease disposition: `"
                + json.dumps(
                    {
                        "disposition": "queued",
                        "message": "BLOCKED_NO_API_MODE",
                        "lease_comment_id": kw.get("denied_lease", 11),
                    }
                )
                + "`.",
                kw.get("denied_at", f"{day}:01:20Z"),
            )
        )
    settlement = {
        "context": {
            "repository": REPO,
            "issue": issue_no,
            "pr": pr_no,
            "head": head,
            "lease": 11,
            "worker_run": kw.get("settled_run", run),
            "worker_attempt": kw.get("settled_attempt", attempt),
        },
        "merge_sha": kw.get("settled_merge", merge),
        "final_state": {"state": "closed", "labels": ["oc-done"]},
    }
    receipts = kw.get("receipts", [settlement])
    if not kw.get("settle", True):
        receipts = []
    for i, receipt in enumerate(receipts):
        comments.append(
            _c(
                15 + i,
                "<!-- OC-HOSTED-SETTLEMENT-V1\n"
                + json.dumps(receipt, sort_keys=True)
                + "\n-->",
                kw.get("settled_at", f"{day}:30:00Z"),
                user=kw.get("settler", BOT),
            )
        )
    checked = kw.get("checked_head", head)
    evidence = CheckerEvidence(
        repository=kw.get("checker_repo", REPO),
        issue_number=issue_no,
        pr_number=pr_no,
        checked_head_sha=checked,
        checker_id=f"anthropic:checker:{6000 + n}:{issue_no}",
        maker_id=kw.get("maker_id", f"anthropic:maker:{run}:{issue_no}"),
        verdict=kw.get("verdict", CheckerVerdict.PASS),
        required_checks_passed=True,
        reason="matches intent",
        material_fingerprint="f" * 16,
        checks_head_sha=checked,
    )
    checker_body = serialize_evidence(evidence)
    if "checker_id" in kw:
        # The engine's constructor refuses a checker that is the maker, so a
        # hand-written record is the only way to present one: forge the text.
        checker_body = checker_body.replace(
            f'"checker_id": "anthropic:checker:{6000 + n}:{issue_no}"',
            f'"checker_id": {json.dumps(kw["checker_id"])}',
        )
    settled = kw.get("settle", True)
    return {
        "repository": kw.get("repository", REPO),
        "issue": {
            "number": issue_no,
            "state": "closed" if settled else "open",
            "state_reason": "completed" if settled else None,
            "labels": [{"name": "oc-done" if settled else "oc-validating"}],
        },
        "comments": comments,
        "pull_request": {
            "number": pr_no,
            "user": kw.get("pr_author", BOT),
            "head": {"sha": head, "ref": branch},
            "base": {"ref": kw.get("pr_base", "oc-autonomous-integration")},
            "body": f"OC-AUTO-ISSUE: #{issue_no}\nOC-AUTO-REQUEUE: false\n",
            "changed_files": kw.get("changed_files", 3),
            "merged": kw.get("pr_merged", True),
            "merge_commit_sha": kw.get("pr_merge_sha", merge),
            "html_url": f"https://github.com/{REPO}/pull/{pr_no}",
        },
        "pr_comments": [_c(20, checker_body, f"{day}:20:00Z")],
        "validation_runs": kw.get(
            "validation_runs", [_vrun(n, head, branch, **kw.get("vrun", {}))]
        ),
        "merge_parents": kw.get("merge_parents", [BASE, head]),
        "merge_on_target": kw.get("merge_on_target", True),
    }


def _ten(changes=None):
    records = [_record(n, recovered=(n == 4)) for n in range(1, 11)]
    for n, kw in (changes or {}).items():
        records[n - 1] = _record(n, recovered=(n == 4), **kw)
    return records


def _evaluate(records, **kw):
    kw.setdefault("window_complete", True)
    return _module().evaluate(records, **kw)


def _broken(n, **kw):
    report = _evaluate(_ten({n: kw}))
    return report, next(c for c in report["cycles"] if c["issue"] == 2000 + n)


# --- certification -----------------------------------------------------------


def test_ten_receipted_independent_cycles_with_a_real_recovery_certify():
    report = _evaluate(_ten())
    assert report["certified"] is True, report["reason"]
    assert report["consecutive_completed"] == 10 and report["recovery_proven"] is True
    first = report["cycles"][0]
    assert all(first["criteria"].values())
    assert first["evidence"]["provider_model"] == "claude-haiku-4-5"
    assert first["evidence"]["maker_id"] == "anthropic:maker:9001:2001"
    fourth = next(c for c in report["cycles"] if c["issue"] == 2004)
    assert fourth["evidence"]["recovered_leases"] == 1
    assert (
        report["cycles"][1]["evidence"]["zero_execution"][0]["reason"]
        == "Bounded ceiling (max_turns)."
    )


def test_one_verified_cycle_is_reported_but_never_certified():
    report = _evaluate([_record(1)])
    assert report["consecutive_completed"] == 1 and report["cycles"][0]["passed"]
    assert report["certified"] is False


def test_ten_clean_cycles_without_a_recovery_do_not_certify():
    report = _evaluate([_record(n) for n in range(1, 11)])
    assert report["consecutive_completed"] == 10 and report["certified"] is False
    assert report["reason"] == "no recovered lease among the consecutive cycles"


def test_caller_chosen_cycles_are_never_certified():
    report = _evaluate(_ten(), window_complete=False)
    assert report["consecutive_completed"] == 10 and report["certified"] is False
    assert "chosen by the caller" in report["reason"]


def test_the_streak_is_the_most_recent_unbroken_run():
    records = [_record(0, settle=False)] + _ten()
    records[0]["issue"]["number"] = 1999
    report = _evaluate(records)
    # The unsettled cycle sorts last, so it is the most recent: streak 0.
    assert report["consecutive_completed"] == 0 and report["certified"] is False
    early_failure = _ten({1: {"verdict": CheckerVerdict.FAIL}}) + [
        _record(11),
        _record(12),
    ]
    report = _evaluate(early_failure)
    assert report["consecutive_completed"] == 11  # 2..12 after the early failure


# --- each criterion, and its binding to the settled attempt -------------------


@pytest.mark.parametrize(
    ("kw", "failure"),
    [
        ({"denied": True}, "PROVIDER_ADMISSION_DENIED"),
        (
            {"checker_id": "anthropic:maker:9005:2005"},
            "NO_INDEPENDENT_PASS_AT_EXACT_HEAD",
        ),
        (
            {"checker_id": "hosted-checker:claude-haiku-4-5"},
            "NO_INDEPENDENT_PASS_AT_EXACT_HEAD",
        ),
        (
            {"maker_id": "anthropic:maker:4242:2005"},
            "NO_INDEPENDENT_PASS_AT_EXACT_HEAD",
        ),
        ({"checker_repo": "someone/else"}, "NO_INDEPENDENT_PASS_AT_EXACT_HEAD"),
        ({"checked_head": "d" * 40}, "NO_INDEPENDENT_PASS_AT_EXACT_HEAD"),
        ({"verdict": CheckerVerdict.FAIL}, "NO_INDEPENDENT_PASS_AT_EXACT_HEAD"),
        ({"verdict": CheckerVerdict.INCONCLUSIVE}, "NO_INDEPENDENT_PASS_AT_EXACT_HEAD"),
        ({"changed_files": 0}, "NO_MAKER_PR_AT_SETTLED_HEAD"),
        ({"unexplained_zero": True}, "ZERO_EXECUTION_WITHOUT_REASON"),
        # unmerged or mis-settled merges
        ({"pr_merged": False}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"pr_merge_sha": "9" * 40}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"settled_merge": "8" * 40}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"pr_base": "main"}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"merge_on_target": False}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"merge_parents": [BASE, "7" * 40]}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"merge_parents": [_sha(5, "a")]}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        # execution evidence bound to the settled worker attempt
        ({"worker_receipt_run": 4242}, "WORKER_NOT_BOUND_TO_SETTLED_ATTEMPT"),
        ({"settled_run": 4242}, "CLAIM_NOT_BOUND_TO_SETTLED_ATTEMPT"),
        ({"settled_attempt": 2}, "CLAIM_NOT_BOUND_TO_SETTLED_ATTEMPT"),
        ({"settled_at": "2026-10-16T05:00:30Z"}, "CLAIM_NOT_BOUND_TO_SETTLED_ATTEMPT"),
        # the maker PR must be the engine's own
        ({"pr_author": OWNER}, "NO_MAKER_PR_AT_SETTLED_HEAD"),
        ({"pr_branch": "feature/hand-made"}, "NO_MAKER_PR_AT_SETTLED_HEAD"),
        ({"pr_branch": "claude-direct/issue-1-9005"}, "NO_MAKER_PR_AT_SETTLED_HEAD"),
        # the validation run must be the one the settlement could rely on
        ({"vrun": {"actor": OWNER}}, "NO_GREEN_VALIDATION_AT_EXACT_HEAD"),
        ({"vrun": {"event": "push"}}, "NO_GREEN_VALIDATION_AT_EXACT_HEAD"),
        ({"vrun": {"head_branch": "main"}}, "NO_GREEN_VALIDATION_AT_EXACT_HEAD"),
        ({"vrun": {"head_sha": "c" * 40}}, "NO_GREEN_VALIDATION_AT_EXACT_HEAD"),
        (
            {"vrun": {"created_at": "2026-10-16T05:01:00Z"}},
            "NO_GREEN_VALIDATION_AT_EXACT_HEAD",
        ),
        (
            {"vrun": {"path": ".github/workflows/other.yml"}},
            "NO_GREEN_VALIDATION_AT_EXACT_HEAD",
        ),
    ],
)
def test_each_missing_or_unbound_criterion_breaks_the_streak(kw, failure):
    report, cycle = _broken(5, **kw)
    assert report["certified"] is False
    assert failure in cycle["failures"], cycle["failures"]
    assert cycle["passed"] is False
    assert report["consecutive_completed"] == 5  # cycles 6..10 after it


def test_a_denial_for_an_earlier_lease_does_not_fail_the_settled_attempt():
    _, cycle = _broken(5, denied=True, denied_lease=8)
    assert cycle["passed"] is True, cycle["failures"]


def test_missing_ambiguous_or_person_written_receipts_are_not_receipts():
    other = {
        "context": {
            "repository": REPO,
            "issue": 2001,
            "pr": 3001,
            "head": _sha(1, "a"),
            "lease": 11,
            "worker_run": 9001,
            "worker_attempt": 1,
        },
        "merge_sha": "6" * 40,
        "final_state": {"state": "closed", "labels": ["oc-done"]},
    }
    real = dict(other, merge_sha=_sha(1, "b"))
    for kw, failure in (
        ({"settle": False}, "NO_DURABLE_SETTLEMENT_RECEIPT"),
        ({"settler": OWNER}, "NO_DURABLE_SETTLEMENT_RECEIPT"),
        ({"receipts": [real, other]}, "AMBIGUOUS_SETTLEMENT_RECEIPTS"),
    ):
        report, cycle = _broken(1, **kw)
        assert failure in cycle["failures"], (kw, cycle["failures"])
        assert report["certified"] is False
    # An identical duplicate (a re-posted receipt) is still one receipt.
    _, cycle = _broken(1, receipts=[real, real])
    assert cycle["passed"] is True, cycle["failures"]


def test_the_settled_validation_run_is_the_highest_id_not_the_list_order():
    head, branch = _sha(3, "a"), "claude-direct/issue-2003-9003"
    older = _vrun(3, head, branch, id=1, conclusion="success")
    newer = _vrun(3, head, branch, id=2, conclusion="failure")
    for runs in ([newer, older], [older, newer]):  # GitHub lists newest first
        _, cycle = _broken(3, validation_runs=runs)
        assert "NO_GREEN_VALIDATION_AT_EXACT_HEAD" in cycle["failures"]
    _, cycle = _broken(
        3,
        validation_runs=[
            _vrun(3, head, branch, id=2),
            _vrun(3, head, branch, id=1, conclusion="failure"),
        ],
    )
    assert cycle["passed"] is True
    # A newer green run that someone else started does not rescue a red bot run.
    person = _vrun(3, head, branch, id=9, actor=OWNER, event="workflow_dispatch")
    _, cycle = _broken(3, validation_runs=[newer, person])
    assert "NO_GREEN_VALIDATION_AT_EXACT_HEAD" in cycle["failures"]


# --- recovery ----------------------------------------------------------------


def test_the_reconcilers_real_receipt_counts_as_a_recovery():
    module = _module()
    cycle = module.evaluate_cycle(_record(4, recovered=True))
    assert cycle["evidence"]["recovered_leases"] == 1
    assert cycle["evidence"]["recovery_receipts"]


@pytest.mark.parametrize(
    "recovery",
    [
        {"comment": 11},  # names the settled claim, not an earlier lease
        {"comment": 999},  # names no claim on this issue
        {"lease": f"{REPO}:1:1:2004"},  # lease id does not match that claim
        {"lease_run": 31337},  # run is not that lease's run
        {"reason": "run_cancelled"},  # not a reason the reconciler emits
        {"released": ["oc-running"]},  # still running: nothing was released
        {"extra": {"released_state": None}},  # no released state at all
        {"extra": {"issue_number": 9999}},  # another issue's receipt
        {"user": OWNER},  # written by a person
    ],
)
def test_recovery_counts_only_for_an_earlier_lease_of_the_same_issue(recovery):
    records = _ten()
    records[3] = _record(4, recovered=True, recovery=recovery)
    report = _evaluate(records)
    fourth = next(c for c in report["cycles"] if c["issue"] == 2004)
    assert fourth["evidence"]["recovered_leases"] == 0
    assert report["consecutive_completed"] == 10 and report["certified"] is False


def test_a_recovery_after_the_settled_claim_does_not_count_but_a_same_second_one_before_does():
    late = _record(4, recovered=True, recovery_at="2026-10-16T04:05:00Z")
    assert _module().evaluate_cycle(late)["evidence"]["recovered_leases"] == 0
    # Reconcile and re-claim inside one controller second: ids order them.
    same = _record(4, recovered=True, recovery_at="2026-10-16T04:01:00Z")
    assert _module().evaluate_cycle(same)["evidence"]["recovered_leases"] == 1


def test_recovery_schema_quoted_in_prose_is_not_a_receipt():
    records = _ten()
    records[3] = _record(4)
    records[5]["comments"].append(
        _c(
            77,
            'see "schema":"oc.swarm-lease-recovery.v1" in the logs',
            "2026-10-16T06:00:30Z",
        )
    )
    report = _evaluate(records)
    assert report["recovery_proven"] is False and report["certified"] is False


# --- reuse, formats, fetching ----------------------------------------------------


@pytest.mark.parametrize("field", ["head_sha", "merge_sha", "lease_id", "pull_request"])
def test_reused_evidence_breaks_the_streak(field):
    module = _module()
    records = _ten()
    first, later = module.evaluate_cycle(records[6]), records[7]
    if field == "head_sha":
        later["pull_request"]["head"]["sha"] = records[6]["pull_request"]["head"]["sha"]
    elif field == "merge_sha":
        for c in later["comments"]:
            c["body"] = c["body"].replace(_sha(8, "b"), _sha(7, "b"))
        later["pull_request"]["merge_commit_sha"] = _sha(7, "b")
    elif field == "lease_id":
        for c in later["comments"]:
            c["body"] = c["body"].replace(
                f"{REPO}:9008:1:2008", first["evidence"]["lease_id"]
            )
    else:
        later["pull_request"]["html_url"] = records[6]["pull_request"]["html_url"]
    report = _evaluate(records)
    assert report["certified"] is False and report["consecutive_completed"] < 10


def test_repository_case_does_not_reject_a_valid_cycle():
    assert (
        _module().evaluate_cycle(_record(1, repository=REPO.upper()))["passed"] is True
    )


def test_real_claim_comment_format_from_issue_1782_parses():
    module = _module()
    body = (
        '[OC-SWARM-V4] Dependency/resource lease claimed: `{"dependencies":[1780],"issue_number":1782,'
        '"lease_id":"jsp1440/orchid-calyx-backend:37577571063:1:1782","material_fingerprint":"858e904f6f33d9a7",'
        '"reads":["control-plane"],"schema":"oc.swarm-claim.v1","writes":["control-plane"]}`.'
    )
    claim = module._json_after(module.CLAIM, body)
    assert (
        claim["lease_id"].endswith(":1782") and claim["schema"] == "oc.swarm-claim.v1"
    )


def _api_for(records, extra=None):
    routes = dict(extra or {})
    for record in records:
        n = record["issue"]["number"]
        pr = record["pull_request"]
        head, merge = pr["head"]["sha"], pr["merge_commit_sha"]
        routes.update(
            {
                f"repos/{REPO}/issues/{n}": record["issue"],
                f"repos/{REPO}/issues/{n}/comments?per_page=100": record["comments"],
                f"repos/{REPO}/pulls/{pr['number']}": pr,
                f"repos/{REPO}/issues/{pr['number']}/comments?per_page=100": record[
                    "pr_comments"
                ],
                f"repos/{REPO}/actions/workflows/orchid-autonomous-validation.yml/runs?head_sha={head}&per_page=20": {
                    "workflow_runs": record["validation_runs"]
                },
                f"repos/{REPO}/git/commits/{merge}": {
                    "parents": [{"sha": p} for p in record["merge_parents"]]
                },
            }
        )
        routes.setdefault(
            f"repos/{REPO}/compare/{merge}...oc-autonomous-integration",
            {"status": "ahead"},
        )
    calls = []

    def api(path):
        calls.append(path)
        return routes[path]

    return api, calls


def test_fetch_record_reads_every_source_read_only():
    module = _module()
    record = _record(1)
    api, calls = _api_for([record])
    assert (
        module.evaluate_cycle(module.fetch_record(REPO, 2001, api=api))["passed"]
        is True
    )
    assert len(calls) == 7


def test_fetch_record_sees_a_merge_missing_from_the_target_branch():
    module = _module()
    record = _record(1)
    merge = record["pull_request"]["merge_commit_sha"]
    api, _ = _api_for(
        [record],
        {
            f"repos/{REPO}/compare/{merge}...oc-autonomous-integration": {
                "status": "diverged"
            }
        },
    )
    cycle = module.evaluate_cycle(module.fetch_record(REPO, 2001, api=api))
    assert "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET" in cycle["failures"]


def test_the_window_includes_every_claimed_issue_so_failures_cannot_be_left_out():
    module = _module()
    records = _ten({6: {"verdict": CheckerVerdict.FAIL}})
    unclaimed = {"number": 4000, "state": "open", "labels": []}
    listing = [r["issue"] for r in records] + [
        unclaimed,
        {"number": 4001, "pull_request": {}},
    ]
    api, _ = _api_for(
        records,
        {
            f"repos/{REPO}/issues?state=all&since=2026-10-16T00:00:00Z&per_page=100": listing,
            f"repos/{REPO}/issues/4000": unclaimed,
            f"repos/{REPO}/issues/4000/comments?per_page=100": [],
        },
    )
    window = module.window_records(REPO, "2026-10-16T00:00:00Z", api=api)
    assert sorted(r["issue"]["number"] for r in window) == list(range(2001, 2011))
    report = module.evaluate(window, window_complete=True)
    assert report["certified"] is False and report["consecutive_completed"] == 4


def test_cli_window_mode_certifies_and_issue_mode_never_does(tmp_path, monkeypatch):
    module = _module()
    records = _ten()
    by_number = {r["issue"]["number"]: r for r in records}
    monkeypatch.setattr(module, "window_records", lambda repo, start: records)
    monkeypatch.setattr(module, "fetch_record", lambda repo, n: by_number[n])
    out = tmp_path / "acceptance-report.json"
    assert (
        module.main(
            [
                "--repository",
                REPO,
                "--window-start",
                "2026-10-16T00:00:00Z",
                "--output",
                str(out),
            ]
        )
        == 0
    )
    report = json.loads(out.read_text())
    assert (
        report["schema"] == "oc.engineering-acceptance-report.v1"
        and report["certified"] is True
    )
    issues = ",".join(str(n) for n in by_number)
    assert (
        module.main(["--repository", REPO, "--issues", issues, "--output", str(out)])
        == 1
    )
    assert json.loads(out.read_text())["certified"] is False


def test_cli_first_cycle_mode_reports_one_verified_cycle(tmp_path, monkeypatch):
    module = _module()
    out = tmp_path / "acceptance-report.json"
    monkeypatch.setattr(module, "window_records", lambda repo, start: [_record(1)])
    args = [
        "--repository",
        REPO,
        "--window-start",
        "2026-10-16T00:00:00Z",
        "--first-cycle",
        "--output",
        str(out),
    ]
    assert module.main(args) == 0
    report = json.loads(out.read_text())
    assert report["certified"] is False and report["cycles"][0]["passed"] is True
    monkeypatch.setattr(
        module, "window_records", lambda repo, start: [_record(1, settle=False)]
    )
    assert module.main(args) == 1
    monkeypatch.setattr(module, "fetch_record", lambda repo, n: _record(1))
    assert (
        module.main(
            [
                "--repository",
                REPO,
                "--issues",
                "2001",
                "--first-cycle",
                "--output",
                str(out),
            ]
        )
        == 1
    )


def test_lists_are_paged_on_repo_paths_not_link_headers(monkeypatch):
    module = _module()
    seen = []

    def fake(path):
        seen.append(path)
        page = int(path.rsplit("page=", 1)[1])
        return [{"id": i} for i in range(100 if page < 3 else 7)]

    monkeypatch.setattr(module, "_gh", fake)
    assert len(module.gh_api(f"repos/{REPO}/issues/1/comments?per_page=100")) == 207
    assert seen == [
        f"repos/{REPO}/issues/1/comments?per_page=100&page={n}" for n in (1, 2, 3)
    ]


def test_a_full_last_page_fetches_one_more_and_a_runaway_list_fails_closed(monkeypatch):
    module = _module()
    pages = []

    def exact(path):
        pages.append(path)
        return [{"id": 1}] * 100 if path.endswith("page=1") else []

    monkeypatch.setattr(module, "_gh", exact)
    assert len(module.gh_api(f"repos/{REPO}/issues/1/comments?per_page=100")) == 100
    assert len(pages) == 2
    monkeypatch.setattr(module, "_gh", lambda path: [{"id": 1}] * 100)
    with pytest.raises(RuntimeError, match="PAGINATION_LIMIT_EXCEEDED"):
        module.gh_api(f"repos/{REPO}/issues/1/comments?per_page=100", max_pages=3)


def test_controller_slots_can_be_bounded_by_a_repository_variable():
    """A bounded demonstration needs scheduled waves to lease one lane, not eight."""
    text = (ROOT / ".github" / "workflows" / "orchid-swarm-controller.yml").read_text()
    expected = (
        "WORKER_SLOTS: ${{ inputs.worker_slots || vars.OC_SWARM_WORKER_SLOTS || '8' }}"
    )
    assert text.count(expected) == 2  # plan and refill read the same bound
    assert "WORKER_SLOTS: ${{ inputs.worker_slots || '8' }}" not in text
