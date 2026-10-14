"""Proposal review and handoff: read-only, gated by the approvals file, once only."""

from __future__ import annotations

import importlib.util
import json
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
