"""acceptance-report.json: only real, independently validated, receipted cycles count.

Fixtures mirror the records the engine writes: the swarm claim
(``lease_id = repo:run:attempt:issue``), the completion lane's worker receipt
(``Run …/actions/runs/<run>``), the maker's draft PR
(``claude-direct/issue-<n>-<run>``, ``OC-AUTO-ISSUE: #<n>``, by the bot), the
checker record (``serialize_evidence``), the hosted settlement receipt and
``oc_swarm_lease_reconcile``'s recovery receipt.
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


def _record(n, **kw):
    issue_no, pr_no = 2000 + n, 3000 + n
    run, attempt = int(f"9{n:03d}"), 1
    head, merge = _sha(n, "a"), _sha(n, "b")
    day = f"2026-10-{16 + n // 24:02d}T{n % 24:02d}"
    comments = []
    if kw.get("recovered"):
        old_run = int(f"7{n:03d}")
        comments.append(_claim(8, issue_no, old_run, 1, f"{day}:00:00Z"))
        recovery = {
            "schema": "oc.swarm-lease-recovery.v1",
            "issue_number": issue_no,
            "action": "recover",
            "reason": "run_cancelled",
            "lease_id": kw.get("recovery_lease", f"{REPO}:{old_run}:1:{issue_no}"),
            "lease_comment_id": kw.get("recovery_comment", 8),
            "run_id": kw.get("recovery_run", old_run),
        }
        comments.append(
            _c(
                10,
                "[OC-SWARM-V4] Stale lease recovered: `"
                + json.dumps(recovery, sort_keys=True)
                + "`.",
                kw.get("recovery_at", f"{day}:00:40Z"),
            )
        )
    comments.append(_claim(11, issue_no, run, attempt, f"{day}:01:00Z"))
    worker_run = kw.get("worker_receipt_run", run)
    comments.append(
        _c(
            12,
            "[OC-AUTO] Completion worker started from workflow_dispatch; economy-policy=one-provider-per-run; "
            "primary=Claude; route=tier=deep; model=claude-opus-5; reason=deep; packet=ffff. "
            f"Run https://github.com/{REPO}/actions/runs/{worker_run}.",
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
                        "nested": {"a": 1},
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
                    {"disposition": "queued", "message": "BLOCKED_NO_API_MODE"}
                )
                + "`.",
                f"{day}:01:20Z",
            )
        )
    settled_merge = kw.get("settled_merge", merge)
    if kw.get("settle", True):
        context = {
            "repository": REPO,
            "issue": issue_no,
            "pr": pr_no,
            "head": head,
            "lease": 11,
            "worker_run": kw.get("settled_run", run),
            "worker_attempt": kw.get("settled_attempt", attempt),
        }
        comments.append(
            _c(
                15,
                "<!-- OC-HOSTED-SETTLEMENT-V1\n"
                + json.dumps(
                    {
                        "context": context,
                        "merge_sha": settled_merge,
                        "final_state": {"state": "closed", "labels": ["oc-done"]},
                    },
                    sort_keys=True,
                )
                + "\n-->",
                f"{day}:30:00Z",
                user=kw.get("settler", BOT),
            )
        )
    checked = kw.get("checked_head", head)
    evidence = CheckerEvidence(
        repository=REPO,
        issue_number=issue_no,
        pr_number=pr_no,
        checked_head_sha=checked,
        checker_id="hosted-checker:claude-haiku-4-5",
        maker_id="completion-lane:claude-opus-5",
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
            '"checker_id": "hosted-checker:claude-haiku-4-5"',
            f'"checker_id": {json.dumps(kw["checker_id"])}',
        )
    pr = {
        "number": pr_no,
        "user": kw.get("pr_author", BOT),
        "head": {
            "sha": head,
            "ref": kw.get("pr_branch", f"claude-direct/issue-{issue_no}-{run}"),
        },
        "base": {"ref": kw.get("pr_base", "oc-autonomous-integration")},
        "body": f"OC-AUTO-ISSUE: #{issue_no}\nOC-AUTO-REQUEUE: false\n",
        "changed_files": kw.get("changed_files", 3),
        "merged": kw.get("pr_merged", True),
        "merge_commit_sha": kw.get("pr_merge_sha", merge),
        "html_url": f"https://github.com/{REPO}/pull/{pr_no}",
    }
    runs = kw.get(
        "validation_runs",
        [
            {
                "id": int(f"8{n:03d}"),
                "head_sha": kw.get("validation_head", head),
                "conclusion": "success",
                "created_at": f"{day}:10:00Z",
                "run_attempt": 1,
                "html_url": f"https://github.com/{REPO}/actions/runs/8{n:03d}",
            }
        ],
    )
    settled = kw.get("settle", True)
    return {
        "repository": REPO,
        "issue": {
            "number": issue_no,
            "state": "closed" if settled else "open",
            "state_reason": "completed" if settled else None,
            "labels": [{"name": "oc-done" if settled else "oc-validating"}],
        },
        "comments": comments,
        "pull_request": pr,
        "pr_comments": [_c(20, checker_body, f"{day}:20:00Z")],
        "validation_runs": runs,
        "merge_parents": kw.get("merge_parents", [BASE, head]),
        "merge_on_target": kw.get("merge_on_target", True),
    }


def _ten(changes=None):
    records = [_record(n, recovered=(n == 4)) for n in range(1, 11)]
    for n, kw in (changes or {}).items():
        records[n - 1] = _record(n, recovered=(n == 4), **kw)
    return records


def _broken(n, **kw):
    report = _module().evaluate(_ten({n: kw}))
    cycle = next(c for c in report["cycles"] if c["issue"] == 2000 + n)
    return report, cycle


def test_ten_receipted_independent_cycles_with_a_recovery_certify():
    report = _module().evaluate(_ten())
    assert report["certified"] is True, report["reason"]
    assert report["consecutive_completed"] == 10 and report["recovery_proven"] is True
    first = report["cycles"][0]
    assert all(first["criteria"].values())
    assert first["evidence"]["provider_model"] == "claude-opus-5"
    assert first["evidence"]["checker_id"] != first["evidence"]["maker_id"]
    fourth = next(c for c in report["cycles"] if c["issue"] == 2004)
    assert fourth["evidence"]["recovered_leases"] == 1
    second = report["cycles"][1]["evidence"]["zero_execution"]
    assert second and second[0]["reason"] == "Bounded ceiling (max_turns)."


def test_one_verified_cycle_is_reported_without_certifying():
    report = _module().evaluate([_record(1)])
    assert report["consecutive_completed"] == 1 and report["cycles"][0]["passed"]
    assert report["certified"] is False


def test_ten_clean_cycles_without_a_recovery_do_not_certify():
    report = _module().evaluate([_record(n) for n in range(1, 11)])
    assert report["consecutive_completed"] == 10 and report["certified"] is False
    assert report["reason"] == "no recovered lease among the consecutive cycles"


@pytest.mark.parametrize(
    ("kw", "failure"),
    [
        ({"denied": True}, "PROVIDER_ADMISSION_DENIED"),
        (
            {"checker_id": "completion-lane:claude-opus-5 "},
            "NO_INDEPENDENT_PASS_AT_EXACT_HEAD",
        ),
        ({"checked_head": "d" * 40}, "NO_INDEPENDENT_PASS_AT_EXACT_HEAD"),
        ({"verdict": CheckerVerdict.FAIL}, "NO_INDEPENDENT_PASS_AT_EXACT_HEAD"),
        ({"verdict": CheckerVerdict.INCONCLUSIVE}, "NO_INDEPENDENT_PASS_AT_EXACT_HEAD"),
        ({"validation_head": "c" * 40}, "NO_GREEN_VALIDATION_AT_EXACT_HEAD"),
        ({"changed_files": 0}, "NO_MAKER_PR_AT_SETTLED_HEAD"),
        ({"unexplained_zero": True}, "ZERO_EXECUTION_WITHOUT_REASON"),
        # Unmerged or mis-settled merges.
        ({"pr_merged": False}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"pr_merge_sha": "9" * 40}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"settled_merge": "8" * 40}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"pr_base": "main"}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"merge_on_target": False}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"merge_parents": [BASE, "7" * 40]}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        ({"merge_parents": [_sha(5, "a")]}, "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET"),
        # Execution evidence bound to the settled worker attempt.
        ({"worker_receipt_run": 4242}, "WORKER_NOT_BOUND_TO_SETTLED_ATTEMPT"),
        ({"settled_run": 4242}, "CLAIM_NOT_BOUND_TO_SETTLED_ATTEMPT"),
        ({"settled_attempt": 2}, "CLAIM_NOT_BOUND_TO_SETTLED_ATTEMPT"),
        # The maker PR must be the engine's own.
        ({"pr_author": OWNER}, "NO_MAKER_PR_AT_SETTLED_HEAD"),
        ({"pr_branch": "feature/hand-made"}, "NO_MAKER_PR_AT_SETTLED_HEAD"),
        ({"pr_branch": "claude-direct/issue-1-9005"}, "NO_MAKER_PR_AT_SETTLED_HEAD"),
    ],
)
def test_each_missing_or_unbound_criterion_breaks_the_streak(kw, failure):
    report, cycle = _broken(5, **kw)
    assert report["certified"] is False
    assert failure in cycle["failures"], cycle["failures"]
    assert cycle["passed"] is False
    assert report["consecutive_completed"] == 4, report["reason"]


def test_a_missing_or_person_written_receipt_is_not_a_receipt():
    for kw in ({"settle": False}, {"settler": OWNER}):
        report, cycle = _broken(1, **kw)
        assert "NO_DURABLE_SETTLEMENT_RECEIPT" in cycle["failures"]
        # Unsettled cycles sort last: nine settled cycles precede it, never ten.
        assert report["certified"] is False and report["consecutive_completed"] == 9


def test_a_newer_failed_validation_overrides_an_older_success():
    head = _sha(3, "a")
    older = {
        "id": 1,
        "head_sha": head,
        "conclusion": "success",
        "created_at": "2026-10-16T03:10:00Z",
        "run_attempt": 1,
    }
    newer = {
        "id": 2,
        "head_sha": head,
        "conclusion": "failure",
        "created_at": "2026-10-16T03:20:00Z",
        "run_attempt": 1,
    }
    # GitHub lists newest first; the order given must not matter.
    for runs in ([newer, older], [older, newer]):
        _, cycle = _broken(3, validation_runs=runs)
        assert "NO_GREEN_VALIDATION_AT_EXACT_HEAD" in cycle["failures"]
    rerun = {**older, "run_attempt": 2, "conclusion": "failure"}
    _, cycle = _broken(3, validation_runs=[older, rerun])
    assert "NO_GREEN_VALIDATION_AT_EXACT_HEAD" in cycle["failures"]
    _, cycle = _broken(
        3,
        validation_runs=[
            {**newer, "conclusion": "success"},
            {**older, "conclusion": "failure"},
        ],
    )
    assert cycle["passed"] is True


@pytest.mark.parametrize(
    "kw",
    [
        {"recovery_comment": 11},  # names the settled claim, not an earlier lease
        {"recovery_comment": 999},  # names no claim on this issue
        {"recovery_lease": f"{REPO}:1:1:2004"},  # lease id does not match that claim
        {"recovery_run": 31337},  # run is not that lease's run
        {"recovery_at": "2026-10-16T04:05:00Z"},  # after the settled claim
    ],
)
def test_recovery_counts_only_for_an_earlier_lease_of_the_same_issue(kw):
    records = _ten()
    records[3] = _record(4, recovered=True, **kw)
    report = _module().evaluate(records)
    fourth = next(c for c in report["cycles"] if c["issue"] == 2004)
    assert fourth["evidence"]["recovered_leases"] == 0
    assert report["consecutive_completed"] == 10 and report["certified"] is False


def test_recovery_text_written_by_a_person_or_quoted_in_prose_does_not_count():
    records = _ten()
    record = records[3]
    for comment in record["comments"]:
        if comment["body"].startswith("[OC-SWARM-V4] Stale lease recovered"):
            comment["user"] = OWNER
    records[5]["comments"].append(
        _c(
            77,
            'see "schema":"oc.swarm-lease-recovery.v1" in the logs',
            "2026-10-16T06:00:30Z",
        )
    )
    report = _module().evaluate(records)
    assert report["recovery_proven"] is False and report["certified"] is False


@pytest.mark.parametrize("field", ["head_sha", "merge_sha", "lease_id", "pull_request"])
def test_reused_evidence_breaks_the_streak(field):
    module = _module()
    records = _ten()
    first, later = module.evaluate_cycle(records[6]), records[7]
    if field == "head_sha":
        later["pull_request"]["head"]["sha"] = records[6]["pull_request"]["head"]["sha"]
    elif field == "merge_sha":
        for c in later["comments"]:
            if "SETTLEMENT" in c["body"]:
                c["body"] = c["body"].replace(_sha(8, "b"), _sha(7, "b"))
        later["pull_request"]["merge_commit_sha"] = _sha(7, "b")
    elif field == "lease_id":
        for c in later["comments"]:
            c["body"] = c["body"].replace(
                f"{REPO}:9008:1:2008", first["evidence"]["lease_id"]
            )
    else:
        later["pull_request"]["html_url"] = records[6]["pull_request"]["html_url"]
    report = module.evaluate(records)
    assert report["certified"] is False and report["consecutive_completed"] < 10


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


def test_fetch_record_reads_every_source_read_only():
    module = _module()
    record = _record(1)
    head, merge = (
        record["pull_request"]["head"]["sha"],
        record["pull_request"]["merge_commit_sha"],
    )
    calls = []

    def api(path):
        calls.append(path)
        routes = {
            f"repos/{REPO}/issues/2001": record["issue"],
            f"repos/{REPO}/issues/2001/comments?per_page=100": record["comments"],
            f"repos/{REPO}/pulls/3001": record["pull_request"],
            f"repos/{REPO}/issues/3001/comments?per_page=100": record["pr_comments"],
            f"repos/{REPO}/actions/workflows/orchid-autonomous-validation.yml/runs?head_sha={head}&per_page=20": {
                "workflow_runs": record["validation_runs"]
            },
            f"repos/{REPO}/git/commits/{merge}": {
                "parents": [{"sha": p} for p in record["merge_parents"]]
            },
            f"repos/{REPO}/compare/{merge}...oc-autonomous-integration": {
                "status": "ahead"
            },
        }
        return routes[path]

    fetched = module.fetch_record(REPO, 2001, api=api)
    assert module.evaluate_cycle(fetched)["passed"] is True
    assert len(calls) == 7


def test_fetch_record_sees_a_merge_missing_from_the_target_branch():
    module = _module()
    record = _record(1)
    head, merge = (
        record["pull_request"]["head"]["sha"],
        record["pull_request"]["merge_commit_sha"],
    )

    def api(path):
        if path.endswith("/compare/" + merge + "...oc-autonomous-integration"):
            return {"status": "diverged"}  # e.g. the branch was reset past the merge
        if "/git/commits/" in path:
            return {"parents": [{"sha": BASE}, {"sha": head}]}
        if "/runs?" in path:
            return {"workflow_runs": record["validation_runs"]}
        if path.endswith("/pulls/3001"):
            return record["pull_request"]
        if "/issues/3001/comments" in path:
            return record["pr_comments"]
        if "/issues/2001/comments" in path:
            return record["comments"]
        return record["issue"]

    cycle = module.evaluate_cycle(module.fetch_record(REPO, 2001, api=api))
    assert "SETTLED_MERGE_NOT_VERIFIED_ON_TARGET" in cycle["failures"]


def test_cli_writes_the_report_and_exits_nonzero_until_certified(tmp_path, monkeypatch):
    module = _module()
    records = {r["issue"]["number"]: r for r in _ten()}
    monkeypatch.setattr(module, "fetch_record", lambda repo, n: records[n])
    out = tmp_path / "acceptance-report.json"
    issues = ",".join(str(n) for n in records)
    assert (
        module.main(["--repository", REPO, "--issues", issues, "--output", str(out)])
        == 0
    )
    report = json.loads(out.read_text())
    assert (
        report["schema"] == "oc.engineering-acceptance-report.v1"
        and report["certified"] is True
    )
    records[2005]["comments"] = [
        c for c in records[2005]["comments"] if "SETTLEMENT" not in c["body"]
    ]
    assert (
        module.main(["--repository", REPO, "--issues", issues, "--output", str(out)])
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
    items = module.gh_api(f"repos/{REPO}/issues/1/comments?per_page=100")
    assert len(items) == 207
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
