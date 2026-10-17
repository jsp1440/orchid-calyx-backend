"""Review the autonomy worker's proposals and hand approved ones to GitHub issues.

The long-running worker (``orchid-calyx-autonomy``) records engineering and
repair work it may not do by itself as *proposals* in its pulse ledger
(``calyx_brain_pulse_ledgers`` in the isolated ``autonomy_prod`` database).
This script is the human gate between a proposal and real work:

``review``
    Reads every proposal with a SELECT-only role inside a READ ONLY
    transaction and writes a JSON and Markdown digest (fingerprint, class,
    origin, state, rationale, evidence).

``handoff``
    Reads the reviewed approvals file (``deploy/autonomy/approvals.json``,
    schema ``oc-autonomy-approvals.v1``, the format the Brain loop reads) and
    plans one GitHub issue per approved proposal. It writes the plan and the
    issue bodies to a directory; the workflow creates the issues. A proposal
    is handed off once: each issue body carries
    ``<!-- oc-autonomy-proposal:<fingerprint> -->`` and fingerprints already
    present in existing issues are skipped.

Approving is a reviewed commit to the approvals file, so every approval is
attributable and revertible. Nothing here writes to the database, merges,
deploys or calls a paid provider; an issue is a request for normal,
reviewed engineering work.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

APPROVALS_SCHEMA = "oc-autonomy-approvals.v1"  # = calyx_brain.autonomy_loop
PLAN_SCHEMA = "oc-autonomy-handoff-plan.v1"
REVIEW_SCHEMA = "oc-autonomy-proposals.v1"
# Classes the loop never runs by itself; scientific and maintenance work is
# executed by the read-only executors and needs no handoff.
HANDOFF_CLASSES = frozenset({"engineering_development", "system_repair"})
HANDOFF_LABEL = "autonomy-handoff"
MARKER = "<!-- oc-autonomy-proposal:{fingerprint} -->"
MARKER_PATTERN = re.compile(r"<!-- oc-autonomy-proposal:([A-Za-z0-9:_.\-]{1,200}) -->")
# A fingerprint is written into an issue marker, so it must match the marker.
FINGERPRINT = re.compile(r"[A-Za-z0-9:_.\-]{1,200}")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
GH_TIMEOUT_SECONDS = 60
DATABASE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")


def _verifier():
    spec = importlib.util.spec_from_file_location(
        "oc_autonomy_hosted_verify",
        Path(__file__).resolve().parent / "oc_autonomy_hosted_verify.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Reading (SELECT-only)
# ---------------------------------------------------------------------------


def load_proposals(dsn: str) -> list[dict[str, Any]]:
    """Every proposal in every pulse ledger, newest ``last_seen`` first."""
    engine = create_engine(dsn, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION READ ONLY"))
            rows = connection.execute(
                text("SELECT ledger_key, state_json FROM calyx_brain_pulse_ledgers")
            ).all()
            connection.rollback()
    finally:
        engine.dispose()
    proposals: list[dict[str, Any]] = []
    for ledger_key, state_json in rows:
        state = json.loads(state_json)
        loop = state.get("loop") or {}
        for fingerprint, proposal in (loop.get("proposals") or {}).items():
            entry = dict(proposal)
            entry["fingerprint"] = str(entry.get("fingerprint") or fingerprint)
            entry["ledger_key"] = ledger_key
            proposals.append(entry)
    proposals.sort(key=lambda p: str(p.get("last_seen", "")), reverse=True)
    return proposals


# ---------------------------------------------------------------------------
# Approvals (the human gate)
# ---------------------------------------------------------------------------


def load_approvals(
    document: Mapping[str, Any], *, now: datetime
) -> dict[str, dict[str, Any]]:
    """Approved fingerprints; expired ones dropped. Same rules as the Brain loop."""
    if document.get("schema") != APPROVALS_SCHEMA:
        raise ValueError("APPROVALS_SCHEMA_UNRECOGNIZED")
    approved: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    for entry in document.get("approvals") or []:
        fingerprint = str(entry.get("fingerprint") or "")
        if not fingerprint or not entry.get("approved_by") or not entry.get("reason"):
            raise ValueError("APPROVAL_ENTRY_INCOMPLETE")
        if not FINGERPRINT.fullmatch(fingerprint):
            raise ValueError("APPROVAL_FINGERPRINT_INVALID")
        if fingerprint in seen:
            raise ValueError("APPROVAL_FINGERPRINT_DUPLICATED")
        seen.add(fingerprint)
        expires = entry.get("expires_at")
        if expires:
            try:
                moment = datetime.fromisoformat(str(expires))
            except ValueError:
                raise ValueError("APPROVAL_EXPIRY_INVALID") from None
            if moment.tzinfo is None:
                # A naive time is ambiguous and cannot be compared with UTC.
                raise ValueError("APPROVAL_EXPIRY_NEEDS_TIMEZONE")
            if moment <= now:
                continue
        approved[fingerprint] = dict(entry)
    return approved


def existing_fingerprints(issues: Iterable[Mapping[str, Any]]) -> set[str]:
    """Fingerprints already handed off, read from issue bodies (any state)."""
    found: set[str] = set()
    for issue in issues:
        found.update(MARKER_PATTERN.findall(str(issue.get("body") or "")))
    return found


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _neutral(value: Any, limit: int) -> str:
    """Proposal text is data: no mentions, no markers, no raw HTML comments."""
    textual = str(value or "")[:limit]
    textual = textual.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    return re.sub(r"@(?=[A-Za-z0-9_-])", "@\u200b", textual)


def issue_title(proposal: Mapping[str, Any]) -> str:
    first = _neutral(proposal.get("rationale"), 500).strip().splitlines()
    summary = (first[0] if first else "") or _neutral(proposal.get("origin"), 200)
    summary = CONTROL.sub(" ", summary).strip()
    if len(summary) > 90:
        summary = summary[:87].rstrip() + "..."
    work_class = CONTROL.sub(" ", _neutral(proposal.get("work_class"), 60))
    return f"[autonomy] {work_class}: {summary}"


def issue_body(
    proposal: Mapping[str, Any],
    approval: Mapping[str, Any],
    source: Mapping[str, Any] | None = None,
) -> str:
    fingerprint = str(proposal["fingerprint"])
    evidence = proposal.get("evidence") or []
    lines = [
        MARKER.format(fingerprint=fingerprint),
        "Approved autonomy proposal handed off by `scripts/oc_autonomy_proposals.py`.",
        "",
        f"- **Work class:** `{_neutral(proposal.get('work_class'), 60)}`",
        f"- **Origin:** `{_neutral(proposal.get('origin'), 200)}`",
        f"- **Fingerprint:** `{fingerprint}`",
        (
            f"- **First seen / last seen:** {_neutral(proposal.get('first_seen'), 40)}"
            f" / {_neutral(proposal.get('last_seen'), 40)}"
        ),
        f"- **Approved by:** {_neutral(approval.get('approved_by'), 80)}",
        f"- **Approval reason:** {_neutral(approval.get('reason'), 500)}",
        f"- **Approval expires:** {_neutral(approval.get('expires_at'), 40) or 'never'}",
        f"- **Approval commit:** `{_neutral((source or {}).get('commit'), 40) or 'unrecorded'}`",
        f"- **Handoff run:** {_neutral((source or {}).get('run_url'), 300) or 'unrecorded'}",
        "",
        "### Rationale",
        "",
        _neutral(proposal.get("rationale"), 500) or "_none recorded_",
        "",
        "### Evidence",
        "",
    ]
    lines += [f"- {_neutral(item, 300)}" for item in evidence[:20]] or [
        "- _none recorded_"
    ]
    lines += [
        "",
        "### Governance",
        "",
        (
            "Normal engineering work: a branch, a pull request, CI and review. "
            "Nothing is merged, deployed or published automatically, and paid "
            "providers stay disabled unless the owner approves them separately."
        ),
    ]
    return "\n".join(lines) + "\n"


def plan_handoff(
    proposals: Iterable[Mapping[str, Any]],
    approvals: Mapping[str, Mapping[str, Any]],
    handed_off: set[str],
    source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    by_fingerprint = {str(p["fingerprint"]): p for p in proposals}
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "create": [],
        "already_handed_off": [],
        "approved_but_not_proposed": [],
        "not_a_handoff_class": [],
        "source": dict(source or {}),
    }
    for fingerprint in sorted(approvals):
        proposal = by_fingerprint.get(fingerprint)
        if proposal is None:
            plan["approved_but_not_proposed"].append(fingerprint)
        elif proposal.get("work_class") not in HANDOFF_CLASSES:
            plan["not_a_handoff_class"].append(fingerprint)
        elif fingerprint in handed_off:
            plan["already_handed_off"].append(fingerprint)
        else:
            plan["create"].append(
                {
                    "fingerprint": fingerprint,
                    "title": issue_title(proposal),
                    "body": issue_body(proposal, approvals[fingerprint], source),
                    "labels": [HANDOFF_LABEL],
                }
            )
    return plan


def review_markdown(proposals: Iterable[Mapping[str, Any]]) -> str:
    rows = list(proposals)
    lines = [
        f"## Autonomy proposals ({len(rows)})",
        "",
        (
            "To approve one, add its fingerprint to `deploy/autonomy/approvals.json` "
            "in a reviewed pull request."
        ),
        "",
        "| State | Class | Origin | Fingerprint | Rationale |",
        "|---|---|---|---|---|",
    ]
    for p in rows:
        rationale = (
            _neutral(p.get("rationale"), 140).replace("|", "\\|").replace("\n", " ")
        )
        lines.append(
            f"| {_neutral(p.get('state'), 40)} | {_neutral(p.get('work_class'), 40)} "
            f"| {_neutral(p.get('origin'), 80).replace('|', '/')} "
            f"| `{p['fingerprint']}` | {rationale} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# GitHub (issues only, through the gh CLI and the workflow's own token)
# ---------------------------------------------------------------------------


class GitHubUnavailable(RuntimeError):
    """GitHub could not be reached or refused; nothing further is attempted."""


def _gh(args: list[str]) -> str:
    if not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")):
        raise GitHubUnavailable("GITHUB_TOKEN_MISSING")
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        raise GitHubUnavailable("GH_CLI_MISSING") from None
    except subprocess.TimeoutExpired:
        raise GitHubUnavailable("GITHUB_TIMEOUT") from None
    if result.returncode != 0:
        detail = CONTROL.sub(" ", result.stderr.strip())[:200]
        raise GitHubUnavailable(f"GITHUB_ERROR: {detail}")
    return result.stdout


def list_handoff_issues(repo: str) -> list[dict[str, Any]]:
    """Every issue ever labelled for handoff, open or closed (one JSON per line)."""
    output = _gh(
        [
            "api",
            "--paginate",
            f"repos/{repo}/issues?labels={HANDOFF_LABEL}&state=all&per_page=100",
            "--jq",
            ".[] | {number, body}",
        ]
    )
    return [json.loads(line) for line in output.splitlines() if line.strip()]


def create_issues(plan_dir: Path, repo: str) -> dict[str, Any]:
    """Open the planned issues. Re-checks markers first; stops at the first error.

    Recovery is a re-run: issues already opened carry their marker and are
    skipped, so a failure part-way never produces a duplicate.
    """
    plan = json.loads((plan_dir / "plan.json").read_text(encoding="utf-8"))
    results: dict[str, Any] = {"created": [], "skipped_existing": [], "error": None}
    try:
        present = existing_fingerprints(list_handoff_issues(repo))
        pending = [i for i in plan["create"] if i["fingerprint"] not in present]
        results["skipped_existing"] = sorted(
            i["fingerprint"] for i in plan["create"] if i["fingerprint"] in present
        )
        if pending:
            _gh(
                [
                    "label",
                    "create",
                    HANDOFF_LABEL,
                    "--repo",
                    repo,
                    "--force",
                    "--color",
                    "0E8A16",
                    "--description",
                    "Approved autonomy proposal handed off for normal reviewed work",
                ]
            )
        for item in pending:
            url = _gh(
                [
                    "issue",
                    "create",
                    "--repo",
                    repo,
                    "--title",
                    item["title"],
                    "--body-file",
                    str(plan_dir / item["body_file"]),
                    "--label",
                    HANDOFF_LABEL,
                ]
            ).strip()
            results["created"].append({"fingerprint": item["fingerprint"], "url": url})
    except GitHubUnavailable as exc:
        results["error"] = str(exc)
    (plan_dir / "results.json").write_text(
        json.dumps(results, indent=1, sort_keys=True), encoding="utf-8"
    )
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _dsn(raw: str, database: str | None) -> str:
    dsn = _verifier().normalize_dsn(raw)
    if database:
        if not DATABASE_NAME.fullmatch(database):
            raise ValueError("DATABASE_NAME_INVALID")
        dsn = make_url(dsn).set(database=database).render_as_string(hide_password=False)
    return dsn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("review", "handoff"):
        command = sub.add_parser(name)
        command.add_argument("--dsn", required=True, help="SELECT-only connection URL")
        command.add_argument("--database", help="database on the same server")
    review = sub.choices["review"]
    review.add_argument("--json", type=Path, required=True)
    review.add_argument("--markdown", type=Path, required=True)
    handoff = sub.choices["handoff"]
    handoff.add_argument("--approvals", type=Path, required=True)
    existing = handoff.add_mutually_exclusive_group(required=True)
    existing.add_argument(
        "--existing-issues",
        type=Path,
        help="JSON list of existing issues (any state) with their bodies",
    )
    existing.add_argument(
        "--github-repo", help="owner/name: list existing handoff issues via gh"
    )
    handoff.add_argument("--out", type=Path, required=True, help="plan directory")
    handoff.add_argument("--approval-commit", help="commit that carried the approvals")
    handoff.add_argument("--run-url", help="workflow run that made the plan")
    create = sub.add_parser("create", help="open the planned issues via gh")
    create.add_argument("--plan-dir", type=Path, required=True)
    create.add_argument("--github-repo", required=True)
    args = parser.parse_args(argv)

    if args.command == "create":
        results = create_issues(args.plan_dir, args.github_repo)
        print(json.dumps(results, sort_keys=True))
        return 1 if results["error"] else 0

    try:
        proposals = load_proposals(_dsn(args.dsn, args.database))
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    if args.command == "review":
        args.json.write_text(
            json.dumps(
                {"schema": REVIEW_SCHEMA, "proposals": proposals},
                indent=1,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        args.markdown.write_text(review_markdown(proposals), encoding="utf-8")
        print(json.dumps({"ok": True, "proposals": len(proposals)}))
        return 0

    try:
        approvals = load_approvals(
            json.loads(args.approvals.read_text(encoding="utf-8")),
            now=datetime.now(UTC),
        )
        if args.github_repo:
            issues = list_handoff_issues(args.github_repo)
        else:
            issues = json.loads(args.existing_issues.read_text(encoding="utf-8"))
    except (ValueError, json.JSONDecodeError, GitHubUnavailable) as exc:
        # Fail closed: without a trustworthy list of handed-off issues no plan
        # is written, so nothing can be opened twice.
        print(json.dumps({"ok": False, "error": str(exc)[:200]}))
        return 1
    source = {
        key: value
        for key, value in (
            ("commit", args.approval_commit),
            ("run_url", args.run_url),
        )
        if value
    }
    plan = plan_handoff(proposals, approvals, existing_fingerprints(issues), source)
    args.out.mkdir(parents=True, exist_ok=True)
    for index, item in enumerate(plan["create"]):
        (args.out / f"issue-{index:03d}.md").write_text(item["body"], encoding="utf-8")
        item["body_file"] = f"issue-{index:03d}.md"
    (args.out / "plan.json").write_text(
        json.dumps(plan, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": True,
                "create": len(plan["create"]),
                "already_handed_off": len(plan["already_handed_off"]),
                "approved_but_not_proposed": plan["approved_but_not_proposed"],
                "not_a_handoff_class": plan["not_a_handoff_class"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
