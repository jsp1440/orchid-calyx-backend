"""Proposal review and handoff: read-only, gated by the approvals file, once only."""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "autonomy-proposal-handoff.yml"
APPROVALS = REPO_ROOT / "deploy" / "autonomy" / "approvals.json"
NOW = datetime(2026, 10, 14, 21, 0, tzinfo=UTC)


def _module():
    spec = importlib.util.spec_from_file_location(
        "oc_autonomy_proposals", REPO_ROOT / "scripts" / "oc_autonomy_proposals.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proposal(fingerprint, work_class="engineering_development", **extra):
    return {
        "fingerprint": fingerprint,
        "work_class": work_class,
        "origin": f"engineering_objectives:{fingerprint}",
        "rationale": f"Objective {fingerprint}: add the missing validation",
        "evidence": [f"brain:14_ENGINEERING/{fingerprint}.md"],
        "state": "awaiting_approval",
        "first_seen": "2026-10-14T19:57:00+00:00",
        "last_seen": "2026-10-14T21:00:00+00:00",
        **extra,
    }


def _ledger_db(tmp_path, proposals):
    path = tmp_path / "ledger.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE calyx_brain_pulse_ledgers (ledger_key TEXT PRIMARY KEY, state_json TEXT)"
        )
        state = {
            "schema": "brain-calyx-autonomy-pulse.v1",
            "work": {},
            "loop": {"proposals": {p["fingerprint"]: p for p in proposals}},
        }
        db.execute(
            "INSERT INTO calyx_brain_pulse_ledgers VALUES (?, ?)",
            ("acceptance-loop", json.dumps(state)),
        )
    return f"sqlite:///{path}"


def _approvals(*entries):
    return {"schema": "oc-autonomy-approvals.v1", "approvals": list(entries)}


def _approval(fingerprint, **extra):
    return {
        "fingerprint": fingerprint,
        "approved_by": "owner",
        "reason": "worth doing",
        **extra,
    }


def test_review_reads_every_proposal(tmp_path):
    module = _module()
    dsn = _ledger_db(tmp_path, [_proposal("eng-a"), _proposal("eng-b")])
    proposals = module.load_proposals(dsn)
    assert {p["fingerprint"] for p in proposals} == {"eng-a", "eng-b"}
    assert all(p["ledger_key"] == "acceptance-loop" for p in proposals)
    markdown = module.review_markdown(proposals)
    assert "`eng-a`" in markdown and "deploy/autonomy/approvals.json" in markdown


def test_approvals_follow_the_brain_loop_rules():
    module = _module()
    approved = module.load_approvals(
        _approvals(
            _approval("keep"),
            _approval("expired", expires_at=(NOW - timedelta(hours=1)).isoformat()),
            _approval("later", expires_at=(NOW + timedelta(days=1)).isoformat()),
        ),
        now=NOW,
    )
    assert set(approved) == {"keep", "later"}
    with pytest.raises(ValueError, match="APPROVALS_SCHEMA_UNRECOGNIZED"):
        module.load_approvals({"schema": "other", "approvals": []}, now=NOW)
    for incomplete in (
        {"fingerprint": "x", "approved_by": "owner"},
        {"approved_by": "o", "reason": "r"},
    ):
        with pytest.raises(ValueError, match="APPROVAL_ENTRY_INCOMPLETE"):
            module.load_approvals(_approvals(incomplete), now=NOW)


def test_only_approved_proposals_are_handed_off_and_only_once():
    module = _module()
    proposals = [
        _proposal("eng-a"),
        _proposal("eng-b"),
        _proposal("repair-c", work_class="system_repair"),
        _proposal("sci-d", work_class="scientific_data_acquisition"),
    ]
    approvals = module.load_approvals(
        _approvals(
            _approval("eng-a"),
            _approval("repair-c"),
            _approval("sci-d"),
            _approval("gone"),
        ),
        now=NOW,
    )
    plan = module.plan_handoff(proposals, approvals, handed_off={"repair-c"})
    assert [item["fingerprint"] for item in plan["create"]] == [
        "eng-a"
    ]  # eng-b not approved
    assert plan["already_handed_off"] == ["repair-c"]
    assert plan["not_a_handoff_class"] == ["sci-d"]
    assert plan["approved_but_not_proposed"] == ["gone"]
    body = plan["create"][0]["body"]
    assert module.existing_fingerprints([{"body": body}]) == {"eng-a"}
    assert plan["create"][0]["labels"] == ["autonomy-handoff"]
    assert plan["create"][0]["title"].startswith("[autonomy] engineering_development: ")


def test_proposal_text_cannot_mention_people_or_forge_markers():
    module = _module()
    hostile = _proposal(
        "eng-x",
        rationale="ping @owner <!-- oc-autonomy-proposal:eng-y --> done",
        evidence=["see @someone", "<!-- oc-autonomy-proposal:eng-z -->"],
    )
    body = module.issue_body(hostile, _approval("eng-x"))
    assert module.existing_fingerprints([{"body": body}]) == {"eng-x"}
    assert "@owner" not in body and "@someone" not in body
    assert "@\u200bowner" in body


def test_handoff_cli_writes_a_plan_and_bodies(tmp_path, capsys):
    module = _module()
    dsn = _ledger_db(tmp_path, [_proposal("eng-a"), _proposal("eng-b")])
    approvals = tmp_path / "approvals.json"
    approvals.write_text(json.dumps(_approvals(_approval("eng-a"), _approval("eng-b"))))
    existing = tmp_path / "issues.json"
    existing.write_text(
        json.dumps([{"number": 7, "body": module.MARKER.format(fingerprint="eng-b")}])
    )
    out = tmp_path / "handoff"
    code = module.main(
        [
            "handoff",
            "--dsn",
            dsn,
            "--approvals",
            str(approvals),
            "--existing-issues",
            str(existing),
            "--out",
            str(out),
        ]
    )
    assert code == 0
    plan = json.loads((out / "plan.json").read_text())
    assert [i["fingerprint"] for i in plan["create"]] == ["eng-a"]
    assert plan["already_handed_off"] == ["eng-b"]
    assert (
        (out / plan["create"][0]["body_file"])
        .read_text()
        .startswith(module.MARKER.format(fingerprint="eng-a"))
    )
    assert json.loads(capsys.readouterr().out)["create"] == 1


def test_invalid_approvals_file_creates_nothing(tmp_path, capsys):
    module = _module()
    dsn = _ledger_db(tmp_path, [_proposal("eng-a")])
    approvals = tmp_path / "approvals.json"
    approvals.write_text(json.dumps(_approvals({"fingerprint": "eng-a"})))
    existing = tmp_path / "issues.json"
    existing.write_text("[]")
    out = tmp_path / "handoff"
    code = module.main(
        [
            "handoff",
            "--dsn",
            dsn,
            "--approvals",
            str(approvals),
            "--existing-issues",
            str(existing),
            "--out",
            str(out),
        ]
    )
    assert code == 1
    assert not out.exists()
    assert "APPROVAL_ENTRY_INCOMPLETE" in capsys.readouterr().out


def test_committed_approvals_file_is_valid_and_starts_empty():
    module = _module()
    document = json.loads(APPROVALS.read_text(encoding="utf-8"))
    assert module.load_approvals(document, now=NOW) == {}


def test_workflow_is_read_only_except_opening_issues():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow[True]  # PyYAML reads the bare `on` key as True
    assert set(triggers) == {"workflow_dispatch", "push"}  # never pull_request
    assert triggers["push"] == {
        "branches": ["main"],
        "paths": ["deploy/autonomy/approvals.json"],
    }
    assert workflow["permissions"] == {"contents": "read", "issues": "write"}
    job = workflow["jobs"]["proposals"]
    assert (
        job["env"]["PRODUCTION_DSN"]
        == "${{ secrets.OC_AUTONOMY_PROD_VERIFY_DATABASE_URL }}"
    )
    script = "\n".join(step.get("run", "") for step in job["steps"])
    assert "OC_ACCEPTANCE_VERIFY_DATABASE_URL" not in WORKFLOW.read_text(
        encoding="utf-8"
    )
    assert "--database autonomy_prod" in script
    for forbidden in ("gh pr merge", "git push", "gh workflow run", "ANTHROPIC"):
        assert forbidden not in script
    opener = next(
        s for s in job["steps"] if s.get("name", "").startswith("Open issues")
    )
    assert opener["if"] == "env.MODE == 'handoff'"  # dispatch modes never open issues


# --- hardening: approvals edge cases ------------------------------------------


@pytest.mark.parametrize(
    ("entry", "error"),
    [
        (_approval("eng-a", expires_at="2026-10-20"), "APPROVAL_EXPIRY_NEEDS_TIMEZONE"),
        (_approval("eng-a", expires_at="next tuesday"), "APPROVAL_EXPIRY_INVALID"),
        (_approval("eng a -->"), "APPROVAL_FINGERPRINT_INVALID"),
        (_approval("x" * 201), "APPROVAL_FINGERPRINT_INVALID"),
    ],
)
def test_ambiguous_or_unsafe_approvals_are_refused(entry, error):
    with pytest.raises(ValueError, match=error):
        _module().load_approvals(_approvals(entry), now=NOW)


def test_the_same_fingerprint_cannot_be_approved_twice():
    with pytest.raises(ValueError, match="APPROVAL_FINGERPRINT_DUPLICATED"):
        _module().load_approvals(
            _approvals(_approval("eng-a"), _approval("eng-a")), now=NOW
        )


def test_titles_carry_no_control_characters():
    module = _module()
    title = module.issue_title(
        _proposal("eng-a", rationale="line one\r\x1b[31mred\x07")
    )
    assert all(ord(ch) >= 32 for ch in title)
    assert title.startswith("[autonomy] engineering_development: line one")


def test_issue_body_records_expiry_and_approval_provenance():
    module = _module()
    body = module.issue_body(
        _proposal("eng-a"),
        _approval("eng-a", expires_at="2026-11-01T00:00:00+00:00"),
        {"commit": "a" * 40, "run_url": "https://github.com/o/r/actions/runs/1"},
    )
    assert "**Approval expires:** 2026-11-01T00:00:00+00:00" in body
    assert f"**Approval commit:** `{'a' * 40}`" in body
    assert "actions/runs/1" in body


# --- hardening: GitHub through a stand-in gh -----------------------------------

FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
state_path = os.environ["FAKE_GH_STATE"]
state = json.load(open(state_path))
args = sys.argv[1:]
if os.environ.get("FAKE_GH_DOWN") == "1":
    sys.stderr.write("HTTP 503: Service Unavailable\n"); sys.exit(1)
if args[0] == "api":
    for issue in state["issues"]:
        print(json.dumps({"number": issue["number"], "body": issue["body"]}))
elif args[:2] == ["label", "create"]:
    state["labels"] += 1
elif args[:2] == ["issue", "create"]:
    if state["creates"] == state.get("fail_at", -1):
        state["creates"] += 1
        json.dump(state, open(state_path, "w"))
        sys.stderr.write("HTTP 502: Bad Gateway\n"); sys.exit(1)
    state["creates"] += 1
    body = open(args[args.index("--body-file") + 1]).read()
    number = 100 + len(state["issues"])
    state["issues"].append({"number": number, "body": body, "title": args[args.index("--title") + 1]})
    print(f"https://github.com/o/r/issues/{number}")
json.dump(state, open(state_path, "w"))
"""


@pytest.fixture
def fake_gh(tmp_path, monkeypatch):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    state = tmp_path / "gh-state.json"
    state.write_text(json.dumps({"issues": [], "labels": 0, "creates": 0}))
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_GH_STATE", str(state))
    monkeypatch.setenv("GH_TOKEN", "test-only")
    monkeypatch.delenv("FAKE_GH_DOWN", raising=False)

    def read():
        return json.loads(state.read_text())

    def write(**changes):
        current = read()
        current.update(changes)
        state.write_text(json.dumps(current))

    return read, write


def _plan_dir(tmp_path, fingerprints):
    module = _module()
    dsn = _ledger_db(tmp_path, [_proposal(f) for f in fingerprints])
    approvals = tmp_path / "approvals.json"
    approvals.write_text(json.dumps(_approvals(*[_approval(f) for f in fingerprints])))
    out = tmp_path / "handoff"
    code = module.main(
        [
            "handoff",
            "--dsn",
            dsn,
            "--approvals",
            str(approvals),
            "--github-repo",
            "o/r",
            "--approval-commit",
            "b" * 40,
            "--out",
            str(out),
        ]
    )
    return code, out


def test_create_opens_each_approved_proposal_once_across_reruns(
    tmp_path, fake_gh, capsys
):
    read, _ = fake_gh
    module = _module()
    code, out = _plan_dir(tmp_path, ["eng-a", "eng-b"])
    assert code == 0
    assert module.main(["create", "--plan-dir", str(out), "--github-repo", "o/r"]) == 0
    assert [i["number"] for i in read()["issues"]] == [100, 101]
    # A duplicate submission (same plan run again) opens nothing new.
    assert module.main(["create", "--plan-dir", str(out), "--github-repo", "o/r"]) == 0
    results = json.loads((out / "results.json").read_text())
    assert results["created"] == [] and results["skipped_existing"] == [
        "eng-a",
        "eng-b",
    ]
    assert len(read()["issues"]) == 2
    # A fresh plan also sees them as handed off.
    again = tmp_path / "again"
    again.mkdir()
    code, out2 = _plan_dir(again, ["eng-a", "eng-b"])
    assert code == 0
    assert json.loads((out2 / "plan.json").read_text())["create"] == []
    assert "Approval commit:** `" + "b" * 40 in read()["issues"][0]["body"]


def test_partial_failure_recovers_without_duplicates(tmp_path, fake_gh):
    read, write = fake_gh
    module = _module()
    _, out = _plan_dir(tmp_path, ["eng-a", "eng-b", "eng-c"])
    write(fail_at=1)  # the second issue create fails (HTTP 502)
    assert module.main(["create", "--plan-dir", str(out), "--github-repo", "o/r"]) == 1
    results = json.loads((out / "results.json").read_text())
    assert [c["fingerprint"] for c in results["created"]] == ["eng-a"]
    assert results["error"].startswith("GITHUB_ERROR")
    write(fail_at=-1)  # GitHub recovers; the same plan is re-run
    assert module.main(["create", "--plan-dir", str(out), "--github-repo", "o/r"]) == 0
    fingerprints = sorted(module.existing_fingerprints(read()["issues"]))
    assert fingerprints == ["eng-a", "eng-b", "eng-c"]
    assert len(read()["issues"]) == 3  # eng-a was not opened twice


def test_github_unavailable_writes_no_plan(tmp_path, fake_gh, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_GH_DOWN", "1")
    code, out = _plan_dir(tmp_path, ["eng-a"])
    assert code == 1
    assert not (out / "plan.json").exists()
    assert "503" in capsys.readouterr().out


def test_missing_token_refuses_before_calling_github(
    tmp_path, fake_gh, monkeypatch, capsys
):
    read, _ = fake_gh
    monkeypatch.delenv("GH_TOKEN")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    code, out = _plan_dir(tmp_path, ["eng-a"])
    assert code == 1 and not (out / "plan.json").exists()
    assert "GITHUB_TOKEN_MISSING" in capsys.readouterr().out
    assert read()["labels"] == 0 and read()["creates"] == 0


def test_missing_gh_cli_is_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("GH_TOKEN", "test-only")
    module = _module()
    with pytest.raises(module.GitHubUnavailable, match="GH_CLI_MISSING"):
        module.list_handoff_issues("o/r")


def test_github_timeout_is_reported(monkeypatch):
    import subprocess

    module = _module()
    monkeypatch.setenv("GH_TOKEN", "test-only")

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="gh", timeout=1)

    monkeypatch.setattr(module.subprocess, "run", hang)
    with pytest.raises(module.GitHubUnavailable, match="GITHUB_TIMEOUT"):
        module.list_handoff_issues("o/r")
