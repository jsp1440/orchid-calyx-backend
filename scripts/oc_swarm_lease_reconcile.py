#!/usr/bin/env python3
"""Reconcile stale ``oc-running`` execution leases before each Swarm wave.

An ``oc-running`` label is the Swarm's execution slot. A worker that is
cancelled, times out, loses its runner, or whose settlement step never ran
leaves that label behind, and the planner then counts a dead worker as an
active lane forever. Dependants stay blocked, and a small queue can reach
``queue > 0`` with zero live workers while every cycle reports "capacity
consumed". This module repairs exactly that gap and nothing else.

Policy (time alone never releases a lease; evidence does):

* A lease with a durable Swarm receipt is released only when the run named in
  the receipt's ``lease_id`` has completed (any conclusion) or no longer
  exists, or when a settlement/release comment was posted after the receipt
  and the label was left behind. A run that is queued/in progress, or whose
  status cannot be read, keeps the slot occupied.
* A lease without a Swarm receipt is a manual/legacy claim. It is released
  only after ``MANUAL_LEASE_MAX_AGE_SECONDS`` measured from the ``labeled``
  timeline event; an unknown label age keeps the slot occupied.
* ``oc-running`` combined with a parked/terminal label is a contradiction the
  health contract already flags; only the stale ``oc-running`` is removed.
* Recovery target: ``oc-validating`` when a durable integration PR (open or
  merged) carries ``OC-AUTO-ISSUE: #N``; otherwise ``oc-queued`` for a bounded
  number of automatic recoveries, then ``oc-blocked`` with an explicit reason.
* Every recovery writes one durable ``[OC-SWARM-V4] Stale lease recovered``
  receipt so the observer and later waves can count it. No provider is ever
  called and no repository file is written.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from scripts.oc_control_plane_health import _is_settlement

SCHEMA = "oc.swarm-lease-reconcile.v1"
RECOVERY_SCHEMA = "oc.swarm-lease-recovery.v1"
RUNNING = "oc-running"
QUEUED = "oc-queued"
VALIDATING = "oc-validating"
BLOCKED = "oc-blocked"
#: Labels that already park or settle an issue; oc-running beside them is stale.
PARKED = frozenset({"oc-done", VALIDATING, BLOCKED, "oc-owner-gate",
                    "oc-runtime-backoff", "oc-repair-backoff"})
#: Manual/legacy leases (no Swarm receipt) expire after one day. Owner-declared
#: local continuations in this repository have used the same horizon.
MANUAL_LEASE_MAX_AGE_SECONDS = 24 * 60 * 60
#: Bounded automatic requeue budget per issue before parking as blocked.
MAX_AUTOMATIC_RECOVERIES = 2
BOT_LOGIN = "github-actions[bot]"
RECOVERY_PREFIX = "[OC-SWARM-V4] Stale lease recovered: `"

_CLAIM = re.compile(
    r"^\[OC-SWARM-V\d+\] Dependency/resource lease claimed: `(\{[^\n]+\})`", re.IGNORECASE
)
_AUTO_ISSUE = re.compile(r"OC-AUTO-ISSUE:\s*#(\d+)")


def _labels(issue: dict) -> set[str]:
    return {x if isinstance(x, str) else str(x.get("name")) for x in issue.get("labels") or []}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_claim(comments: Iterable[dict], *, repository: str, number: int) -> dict | None:
    """Return the newest authenticated Swarm claim receipt bound to this issue."""
    latest = None
    for comment in comments:
        if (comment.get("user") or {}).get("login") != BOT_LOGIN:
            continue
        match = _CLAIM.match(str(comment.get("body") or ""))
        if not match:
            continue
        try:
            claim = json.loads(match.group(1))
        except ValueError:
            continue
        lease_id = str(claim.get("lease_id") or "")
        parts = lease_id.split(":")
        if (claim.get("schema") != "oc.swarm-claim.v1" or claim.get("issue_number") != number
                or len(parts) != 4 or parts[0] != repository or parts[3] != str(number)
                or not parts[1].isdigit() or not parts[2].isdigit()):
            continue
        created = _parse_time(comment.get("created_at"))
        if latest is None or (created and latest["created_at"] and created > latest["created_at"]):
            latest = {"comment_id": comment.get("id"), "lease_id": lease_id,
                      "run_id": int(parts[1]), "run_attempt": int(parts[2]),
                      "created_at": created}
    return latest


def _settled_after(comments: Iterable[dict], claim: dict) -> bool:
    for comment in comments:
        if (comment.get("user") or {}).get("login") != BOT_LOGIN:
            continue
        created = _parse_time(comment.get("created_at"))
        if claim["created_at"] and created and created <= claim["created_at"]:
            continue
        if comment.get("id") == claim["comment_id"]:
            continue
        if _is_settlement(str(comment.get("body") or "")):
            return True
    return False


def _recovery_count(comments: Iterable[dict]) -> int:
    return sum(
        1 for c in comments
        if (c.get("user") or {}).get("login") == BOT_LOGIN
        and str(c.get("body") or "").startswith(RECOVERY_PREFIX)
    )


def durable_pr_index(pull_requests: Iterable[dict]) -> dict[int, dict]:
    """Map issue number -> open or merged integration PR carrying its marker."""
    index: dict[int, dict] = {}
    for pr in pull_requests or []:
        state = str(pr.get("state") or "").upper()
        merged = bool(pr.get("mergedAt") or pr.get("merged_at") or state == "MERGED")
        if state != "OPEN" and not merged:
            continue
        for raw in _AUTO_ISSUE.findall(str(pr.get("body") or "")):
            issue = int(raw)
            current = index.get(issue)
            if current is None or int(pr["number"]) < int(current["number"]):
                index[issue] = {"number": int(pr["number"]), "merged": merged, "state": state}
    return index


def classify_lease(
    issue: dict,
    comments: list[dict],
    *,
    repository: str,
    run_status: Callable[[int], str],
    labeled_at: datetime | None,
    durable_pr: dict | None,
    now: datetime,
) -> dict:
    """Decide, without mutating anything, whether one oc-running lease is stale."""
    number = int(issue["number"])
    labels = _labels(issue)
    decision: dict[str, Any] = {
        "schema": RECOVERY_SCHEMA, "issue_number": number, "action": "keep",
        "reason": None, "target": None, "lease_id": None, "lease_comment_id": None,
        "run_id": None, "run_status": None, "lease_age_seconds": None,
        "recoveries_before": _recovery_count(comments),
        "durable_pr": None if durable_pr is None else durable_pr["number"],
    }
    if str(issue.get("state") or "OPEN").upper() != "OPEN" or RUNNING not in labels:
        decision["reason"] = "not_running"
        return decision

    if labels & PARKED:
        decision.update(action="recover", reason="running_label_beside_parked_state",
                        target=None)
        return decision

    claim = _latest_claim(comments, repository=repository, number=number)
    if claim is not None:
        decision.update(lease_id=claim["lease_id"], lease_comment_id=claim["comment_id"],
                        run_id=claim["run_id"])
        if claim["created_at"] is not None:
            decision["lease_age_seconds"] = int((now - claim["created_at"]).total_seconds())
        if _settled_after(comments, claim):
            decision.update(action="recover", reason="settled_without_label_release")
        else:
            status = run_status(claim["run_id"])
            decision["run_status"] = status
            if status in {"completed", "missing"}:
                decision.update(action="recover", reason="worker_run_terminated_without_settlement")
            else:
                decision["reason"] = "worker_run_active_or_unknown"
                return decision
    else:
        if labeled_at is None:
            decision["reason"] = "manual_lease_age_unknown"
            return decision
        age = int((now - labeled_at).total_seconds())
        decision["lease_age_seconds"] = age
        if age <= MANUAL_LEASE_MAX_AGE_SECONDS:
            decision["reason"] = "manual_lease_within_horizon"
            return decision
        decision.update(action="recover", reason="manual_lease_expired")

    if durable_pr is not None:
        decision["target"] = VALIDATING
    elif decision["recoveries_before"] < MAX_AUTOMATIC_RECOVERIES:
        decision["target"] = QUEUED
    else:
        decision["target"] = BLOCKED
        decision["reason"] = f"{decision['reason']}:automatic_recoveries_exhausted"
    return decision


# ---------------------------------------------------------------------------
# GitHub transport (gh CLI). Never interpolates issue text into a shell.
# ---------------------------------------------------------------------------


class GitHubTransport:
    def __init__(self, repository: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("invalid repository")
        self.repository = repository

    def _run(self, args: list[str], payload: dict | None = None) -> Any:
        result = subprocess.run(
            ["gh", *args], input=json.dumps(payload) if payload is not None else None,
            capture_output=True, text=True, timeout=60, check=True,
        )
        text = result.stdout.strip()
        return json.loads(text) if text.startswith(("{", "[")) else None

    def _paged(self, path: str) -> list[dict]:
        rows: list[dict] = []
        for page in range(1, 11):
            batch = self._run(["api", f"repos/{self.repository}/{path}?per_page=100&page={page}"])
            if not isinstance(batch, list):
                break
            rows.extend(batch)
            if len(batch) < 100:
                break
        return rows

    def running_issues(self) -> list[dict]:
        rows = self._run(["issue", "list", "--repo", self.repository, "--state", "open",
                          "--label", RUNNING, "--limit", "200",
                          "--json", "number,title,body,state,labels,updatedAt"])
        return list(rows or [])

    def pull_requests(self) -> list[dict]:
        rows = self._run(["pr", "list", "--repo", self.repository, "--state", "all",
                          "--base", "oc-autonomous-integration", "--limit", "200",
                          "--json", "number,state,body,mergedAt"])
        return list(rows or [])

    def comments(self, number: int) -> list[dict]:
        return self._paged(f"issues/{number}/comments")

    def labeled_at(self, number: int) -> datetime | None:
        latest = None
        for event in self._paged(f"issues/{number}/timeline"):
            if event.get("event") != "labeled" or (event.get("label") or {}).get("name") != RUNNING:
                continue
            created = _parse_time(event.get("created_at"))
            if created and (latest is None or created > latest):
                latest = created
        return latest

    def run_status(self, run_id: int) -> str:
        try:
            run = self._run(["api", f"repos/{self.repository}/actions/runs/{run_id}"])
        except subprocess.CalledProcessError as exc:
            return "missing" if "HTTP 404" in (exc.stderr or "") else "unknown"
        except (OSError, subprocess.SubprocessError, ValueError):
            return "unknown"
        return str((run or {}).get("status") or "unknown")

    def issue(self, number: int) -> dict:
        return self._run(["issue", "view", str(number), "--repo", self.repository,
                          "--json", "number,title,body,state,labels"])

    def edit_labels(self, number: int, *, remove: list[str], add: list[str]) -> None:
        args = ["issue", "edit", str(number), "--repo", self.repository]
        for label in remove:
            args += ["--remove-label", label]
        for label in add:
            args += ["--add-label", label]
        self._run(args)

    def comment(self, number: int, body: str) -> dict:
        return self._run(["api", "--method", "POST",
                          f"repos/{self.repository}/issues/{number}/comments", "--input", "-"],
                         {"body": body}) or {}


def apply_recovery(transport: GitHubTransport, decision: dict, *, controller_run_url: str) -> dict:
    """Release one stale lease and write its durable recovery receipt."""
    number = decision["issue_number"]
    remove = [RUNNING]
    add = []
    if decision["target"] == QUEUED:
        add = [QUEUED]
    elif decision["target"] == VALIDATING:
        remove.append(QUEUED)
        add = [VALIDATING]
    elif decision["target"] == BLOCKED:
        remove.append(QUEUED)
        add = [BLOCKED]
    transport.edit_labels(number, remove=remove, add=add)
    current = transport.issue(number)
    if RUNNING in _labels(current):
        raise ValueError("stale lease release unconfirmed")
    receipt = {k: v for k, v in decision.items() if k != "action"}
    receipt["released_state"] = sorted(_labels(current))
    body = (RECOVERY_PREFIX + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
            + f"`. Controller run: {controller_run_url}.")
    saved = transport.comment(number, body)
    if saved.get("body") != body or not saved.get("id"):
        raise ValueError("recovery receipt unconfirmed")
    return {**decision, "recovery_comment_id": saved["id"]}


def reconcile(
    transport: GitHubTransport,
    *,
    run_id: int,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict:
    now = now or datetime.now(timezone.utc)
    controller_run_url = f"https://github.com/{transport.repository}/actions/runs/{run_id}"
    running = transport.running_issues()
    durable = durable_pr_index(transport.pull_requests())
    recovered: list[dict] = []
    kept: list[dict] = []
    errors: list[dict] = []
    for issue in running:
        number = int(issue["number"])
        try:
            comments = transport.comments(number)
            decision = classify_lease(
                issue, comments, repository=transport.repository,
                run_status=transport.run_status,
                labeled_at=transport.labeled_at(number),
                durable_pr=durable.get(number), now=now,
            )
            if decision["action"] != "recover":
                kept.append(decision)
                continue
            if dry_run:
                recovered.append({**decision, "dry_run": True})
                continue
            recovered.append(apply_recovery(transport, decision, controller_run_url=controller_run_url))
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
            # Never expose issue text or raw API errors; never retry a write blindly.
            errors.append({"issue": number, "reason": "lease_reconcile_unconfirmed",
                           "error_type": type(exc).__name__})
    return {
        "schema": SCHEMA, "run_id": run_id, "generated_at": now.isoformat().replace("+00:00", "Z"),
        "running_count": len(running), "recovered_count": len(recovered),
        "running_after": len(running) - len(recovered), "recovered": recovered,
        "kept": kept, "errors": errors, "dry_run": dry_run,
        "safety": {"provider_calls": False, "repository_writes": False,
                   "time_alone_releases_lease": False,
                   "max_automatic_recoveries": MAX_AUTOMATIC_RECOVERIES,
                   "manual_lease_max_age_seconds": MANUAL_LEASE_MAX_AGE_SECONDS},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--github-output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    report = reconcile(GitHubTransport(args.repository), run_id=args.run_id, dry_run=args.dry_run)
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"recovered_count={report['recovered_count']}\n")
            handle.write(f"running_after={report['running_after']}\n")
            handle.write(f"reconcile_errors={len(report['errors'])}\n")
    json.dump(report, sys.stdout, sort_keys=True, default=str)
    sys.stdout.write("\n")
    # Recovery errors are evidence for the observer, not a reason to stop the wave.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
