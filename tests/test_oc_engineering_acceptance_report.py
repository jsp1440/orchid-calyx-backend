"""acceptance-report.json: only real, independently validated, receipted cycles count."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app.calyx_orchestrator.checker_dispatch import CheckerEvidence, serialize_evidence
from app.calyx_orchestrator.factory_policy import CheckerVerdict

REPO = "jsp1440/orchid-calyx-backend"
ROOT = Path(__file__).resolve().parents[1]
BOT = {"login": "github-actions[bot]"}
OWNER = {"login": "jsp1440"}


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


def _record(
    n,
    *,
    recovered=False,
    denied=False,
    checker_id="hosted-checker:claude-haiku-4-5",
    maker_id="completion-lane:claude-opus-5",
    checked_head=None,
    validation_head=None,
    settle=True,
    verdict=CheckerVerdict.PASS,
    zero_reason="Bounded ceiling (max_turns).",
    changed_files=3,
    user=BOT,
):
    issue_no, pr_no = 2000 + n, 3000 + n
    head, merge = _sha(n, "a"), _sha(n, "b")
    day = f"2026-10-{16 + n // 24:02d}T{n % 24:02d}"
    claim = {
        "issue_number": issue_no,
        "lease_id": f"{REPO}:9{n}:1:{issue_no}",
        "schema": "oc.swarm-claim.v1",
        "dependencies": [],
        "reads": [],
        "writes": [],
        "material_fingerprint": "f" * 16,
    }
    comments = []
    if recovered:
        comments.append(
            _c(
                10,
                "[OC-SWARM-V4] Expired lease recovered: `"
                + json.dumps(
                    {"schema": "oc.swarm-lease-recovery.v1", "issue_number": issue_no}
                )
                + "`.",
                f"{day}:00:00Z",
            )
        )
    comments += [
        _c(
            11,
            "[OC-SWARM-V4] Dependency/resource lease claimed: `"
            + json.dumps(claim, separators=(",", ":"))
            + "`.",
            f"{day}:01:00Z",
        ),
        _c(
            12,
            "[OC-AUTO] Completion worker started from workflow_dispatch; economy-policy=one-provider-per-run; "
            "primary=Claude; route=tier=deep; model=claude-opus-5; reason=deep; packet=ffff. "
            f"Run https://github.com/{REPO}/actions/runs/9{n}.",
            f"{day}:01:10Z",
        ),
    ]
    if zero_reason is not None and n == 2:
        comments.append(
            _c(
                9,
                "[OC-SWARM-V4] Worker result validated; requested lease disposition: `"
                + json.dumps(
                    {
                        "disposition": "repair",
                        "message": zero_reason,
                        "nested": {"a": 1},
                    }
                )
                + "`.",
                f"{day}:00:30Z",
            )
        )
    if zero_reason is None:
        comments.append(
            _c(
                9,
                "[OC-SWARM-V4] Worker result validated; requested lease disposition: `"
                + json.dumps({"disposition": "runtime-backoff"})
                + "`.",
                f"{day}:00:30Z",
            )
        )
    if denied:
        comments.append(
            _c(
                13,
                "[OC-SWARM-V4] Provider admission denied; requested lease disposition: `"
                + json.dumps(
                    {"disposition": "queued", "message": "BLOCKED_NO_API_MODE"}
                )
                + "`.",
                f"{day}:01:20Z",
            )
        )
    if settle:
        context = {
            "issue": issue_no,
            "pr": pr_no,
            "head": head,
            "lease": 11,
            "worker_run": 9,
        }
        comments.append(
            _c(
                14,
                "<!-- OC-HOSTED-SETTLEMENT-V1\n"
                + json.dumps(
                    {
                        "context": context,
                        "merge_sha": merge,
                        "final_state": {"state": "closed", "labels": ["oc-done"]},
                    },
                    sort_keys=True,
                )
                + "\n-->",
                f"{day}:30:00Z",
                user=user,
            )
        )
    evidence = CheckerEvidence(
        repository=REPO,
        issue_number=issue_no,
        pr_number=pr_no,
        checked_head_sha=checked_head or head,
        checker_id="hosted-checker:claude-haiku-4-5",
        maker_id=maker_id,
        verdict=verdict,
        required_checks_passed=True,
        reason="matches intent",
        material_fingerprint="f" * 16,
        checks_head_sha=checked_head or head,
    )
    return {
        "issue": {
            "number": issue_no,
            "state": "closed" if settle else "open",
            "state_reason": "completed" if settle else None,
            "labels": [{"name": "oc-done" if settle else "oc-validating"}],
        },
        "comments": comments,
        "pull_request": {
            "number": pr_no,
            "head": {"sha": head},
            "changed_files": changed_files,
            "html_url": f"https://github.com/{REPO}/pull/{pr_no}",
        },
        # A hand-written record may name the maker as checker; the engine's own
        # constructor refuses that, so forge it in the serialized text.
        "pr_comments": [
            _c(
                20,
                serialize_evidence(evidence).replace(
                    '"checker_id": "hosted-checker:claude-haiku-4-5"',
                    f'"checker_id": {json.dumps(checker_id)}',
                ),
                f"{day}:20:00Z",
            )
        ],
        "validation_runs": [
            {
                "head_sha": validation_head or head,
                "conclusion": "success",
                "html_url": f"https://github.com/{REPO}/actions/runs/8{n}",
            }
        ],
    }


def _ten(changes=None):
    records = [_record(n, recovered=(n == 4)) for n in range(1, 11)]
    for n, kw in (changes or {}).items():
        records[n - 1] = _record(n, recovered=(n == 4), **kw)
    return records


def test_ten_receipted_independent_cycles_with_a_recovery_certify():
    report = _module().evaluate(_ten())
    assert report["certified"] is True, report["reason"]
    assert report["consecutive_completed"] == 10 and report["recovery_proven"] is True
    first = report["cycles"][0]
    assert all(first["criteria"].values())
    assert first["evidence"]["provider_model"] == "claude-opus-5"
    assert first["evidence"]["checker_id"] != first["evidence"]["maker_id"]
    # A cycle may carry an earlier zero-execution attempt; its reason is preserved.
    second = report["cycles"][1]["evidence"]["zero_execution"]
    assert second and second[0]["reason"] == "Bounded ceiling (max_turns)."


def test_ten_clean_cycles_without_a_recovery_do_not_certify():
    records = [_record(n) for n in range(1, 11)]
    report = _module().evaluate(records)
    assert report["consecutive_completed"] == 10 and report["certified"] is False
    assert report["reason"] == "no recovered lease among the consecutive cycles"


def _broken(n, **kw):
    return _module().evaluate(_ten({n: kw}))


def test_each_missing_criterion_breaks_the_streak_at_that_cycle():
    cases = {
        "PROVIDER_ADMISSION_DENIED": {"denied": True},
        "NO_INDEPENDENT_PASS_AT_EXACT_HEAD": {
            "checker_id": "completion-lane:claude-opus-5 "
        },
        "NO_GREEN_VALIDATION_AT_EXACT_HEAD": {"validation_head": "c" * 40},
        "NO_DURABLE_SETTLEMENT_RECEIPT": {"settle": False},
        "NO_MAKER_PR_AT_SETTLED_HEAD": {"changed_files": 0},
        "ZERO_EXECUTION_WITHOUT_REASON": {"zero_reason": None},
    }
    for failure, kw in cases.items():
        report = _broken(6, **kw)
        assert report["certified"] is False, failure
        broken = next(c for c in report["cycles"] if c["issue"] == 2006)
        assert failure in broken["failures"], (failure, broken["failures"])
        # Ordered by settlement time: an unsettled cycle sorts last, so nine
        # settled cycles still precede it and the set never reaches ten.
        expected = 9 if failure == "NO_DURABLE_SETTLEMENT_RECEIPT" else 5
        assert report["consecutive_completed"] == expected, (failure, report["reason"])


def test_a_checker_that_reviewed_a_different_head_does_not_count():
    report = _broken(3, checked_head="d" * 40)
    assert report["consecutive_completed"] == 2
    assert "NO_INDEPENDENT_PASS_AT_EXACT_HEAD" in report["reason"]


def test_a_failing_or_inconclusive_checker_does_not_count():
    for verdict in (CheckerVerdict.FAIL, CheckerVerdict.INCONCLUSIVE):
        assert _broken(1, verdict=verdict)["consecutive_completed"] == 0


def test_receipts_posted_by_a_person_are_not_engine_receipts():
    # The owner identity is shared by every agent; a hand-written settlement must not count.
    report = _broken(1, user=OWNER)
    assert report["certified"] is False and report["consecutive_completed"] == 9
    assert "NO_DURABLE_SETTLEMENT_RECEIPT" in report["reason"]


def test_reused_evidence_breaks_the_streak():
    records = _ten()
    records[7]["pull_request"]["head"]["sha"] = records[6]["pull_request"]["head"][
        "sha"
    ]
    report = _module().evaluate(records)
    assert report["consecutive_completed"] < 10 and report["certified"] is False


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


def test_fetch_record_reads_issue_pr_checker_and_validation(tmp_path):
    module = _module()
    record = _record(1)
    calls = []

    def api(path):
        calls.append(path)
        if path.endswith("/issues/2001"):
            return record["issue"]
        if path.startswith(f"repos/{REPO}/issues/2001/comments"):
            return record["comments"]
        if path.endswith("/pulls/3001"):
            return record["pull_request"]
        if path.startswith(f"repos/{REPO}/issues/3001/comments"):
            return record["pr_comments"]
        if "orchid-autonomous-validation.yml/runs?head_sha=" in path:
            return {"workflow_runs": record["validation_runs"]}
        raise AssertionError(path)

    fetched = module.fetch_record(REPO, 2001, api=api)
    assert module.evaluate_cycle(fetched)["passed"] is True
    assert len(calls) == 5 and not any("POST" in c for c in calls)


def test_cli_writes_the_report_and_exits_nonzero_until_certified(
    tmp_path, monkeypatch, capsys
):
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
    assert all(p.startswith("repos/") for p in seen)


def test_controller_slots_can_be_bounded_by_a_repository_variable():
    """A bounded demonstration needs scheduled waves to lease one lane, not eight."""
    text = (ROOT / ".github" / "workflows" / "orchid-swarm-controller.yml").read_text()
    expected = (
        "WORKER_SLOTS: ${{ inputs.worker_slots || vars.OC_SWARM_WORKER_SLOTS || '8' }}"
    )
    assert text.count(expected) == 2  # plan and refill read the same bound
    assert "WORKER_SLOTS: ${{ inputs.worker_slots || '8' }}" not in text
