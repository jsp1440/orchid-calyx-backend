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
* A lease on an issue that is already parked (blocked or in backoff) whose
  run ended without any receipt settling it (#1396: two runs claimed one
  packet and only one was released) gets a recovery receipt naming it. The
  labels are already right, so none is edited, and the receipt does not spend
  the issue's automatic requeue budget. Only a few parked issues are read per
  wave, chosen by the run id, so every one is reached over successive waves.
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
PARKED = frozenset(
    {
        "oc-done",
        VALIDATING,
        BLOCKED,
        "oc-owner-gate",
        "oc-scientific-gate",
        "oc-runtime-backoff",
        "oc-repair-backoff",
    }
)
#: Manual/legacy leases (no Swarm receipt) expire after one day. Owner-declared
#: local continuations in this repository have used the same horizon.
MANUAL_LEASE_MAX_AGE_SECONDS = 24 * 60 * 60
#: Bounded automatic requeue budget per issue before parking as blocked.
MAX_AUTOMATIC_RECOVERIES = 2
BOT_LOGIN = "github-actions[bot]"
RECOVERY_PREFIX = "[OC-SWARM-V4] Stale lease recovered: `"
#: A worker run that opened its PR but then ended without success (#1938: the
#: controller run was cancelled after dispatching the worker) leaves the issue
#: in oc-validating with a PR no checker will ever consume, because the hosted
#: checker only trusts a successful controller run. Only these definite
#: conclusions qualify; anything else (success, unknown, still running) is kept.
STRANDED_REASON = "validating_worker_run_unsuccessful"
UNSUCCESSFUL_CONCLUSIONS = frozenset(
    {"cancelled", "failure", "timed_out", "startup_failure"}
)
#: Parked states whose leases the health observer still reads (and reports as
#: orphaned when nothing settled them).
LEASE_PARKED = (BLOCKED, "oc-runtime-backoff", "oc-repair-backoff")
PARKED_LEASE_REASON = "parked_lease_run_terminated_without_settlement"
#: Parked issues read per wave. The controller runs every five minutes, and each
#: read issue costs its full comment history against the shared Actions token.
PARKED_SCAN_PER_WAVE = 3

_CLAIM = re.compile(
    r"^\[OC-SWARM-V\d+\] Dependency/resource lease claimed: `(\{[^\n]+\})`",
    re.IGNORECASE,
)
_AUTO_ISSUE = re.compile(r"OC-AUTO-ISSUE:\s*#(\d+)")
_RECEIPT_JSON = re.compile(r"`(\{[^\n]+\})`")
#: Receipts that settle only the claim they name. The health observer reads
#: them that way, so a parked lease is judged by the same rule: a release for
#: one claim (#1396's second) never settles another (#1396's first).
_BOUND_RELEASE_PREFIXES = (
    "[OC-AUTO] Swarm governor blocked provider execution before credentials were initialized.",
    "[OC-SWARM-V4] Provider admission denied;",
    "[OC-SWARM-V4] Worker result validated; requested lease disposition",
)
_GOVERNOR_RUN = re.compile(r"/actions/runs/(\d+)\.$")


def _labels(issue: dict) -> set[str]:
    return {
        x if isinstance(x, str) else str(x.get("name"))
        for x in issue.get("labels") or []
    }


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


def _claims(comments: Iterable[dict], *, repository: str, number: int) -> list[dict]:
    """Every authenticated Swarm claim receipt bound to this issue, in order."""
    claims = []
    for comment in comments:
        if (comment.get("user") or {}).get("login") != BOT_LOGIN:
            continue
        match = _CLAIM.match(str(comment.get("body") or ""))
        if not match:
            if str(comment.get("body") or "").startswith(
                "[OC-SWARM-V4] Dependency/resource lease claimed:"
            ):
                raise ValueError("malformed_authenticated_claim")
            continue
        try:
            claim = json.loads(match.group(1))
        except ValueError:
            raise ValueError("malformed_authenticated_claim") from None
        lease_id = str(claim.get("lease_id") or "")
        parts = lease_id.split(":")
        if (
            claim.get("schema") != "oc.swarm-claim.v1"
            or claim.get("issue_number") != number
            or len(parts) != 4
            or parts[0] != repository
            or parts[3] != str(number)
            or not parts[1].isdigit()
            or not parts[2].isdigit()
        ):
            raise ValueError("malformed_authenticated_claim")
        created = _parse_time(comment.get("created_at"))
        if (
            created is None
            or type(comment.get("id")) is not int
            or comment["id"] < 1
            or type(claim.get("issue_number")) is not int
            or int(parts[1]) < 1
            or int(parts[2]) < 1
        ):
            raise ValueError("malformed_authenticated_claim")
        claims.append(
            {
                "comment_id": comment.get("id"),
                "lease_id": lease_id,
                "run_id": int(parts[1]),
                "run_attempt": int(parts[2]),
                "created_at": created,
            }
        )
    return claims


def _latest_claim(
    comments: Iterable[dict], *, repository: str, number: int
) -> dict | None:
    """Return the newest authenticated Swarm claim receipt bound to this issue."""
    latest = None
    for claim in _claims(comments, repository=repository, number=number):
        created = claim["created_at"]
        if (
            latest is None
            or (created and latest["created_at"] and created > latest["created_at"])
            or (
                created == latest["created_at"]
                and int(claim["comment_id"] or 0) > int(latest["comment_id"] or 0)
            )
        ):
            latest = claim
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


def _names_lease(comment: dict, claim: dict) -> bool:
    """A later bot receipt whose JSON names this claim's comment id."""
    if (comment.get("user") or {}).get("login") != BOT_LOGIN:
        return False
    if comment.get("id") == claim["comment_id"]:
        return False
    match = _RECEIPT_JSON.search(str(comment.get("body") or ""))
    if not match:
        return False
    try:
        receipt = json.loads(match.group(1))
    except ValueError:
        return False
    return (
        isinstance(receipt, dict)
        and type(receipt.get("lease_comment_id")) is int
        and receipt["lease_comment_id"] == claim["comment_id"]
    )


def _settles_parked_claim(comment: dict, claim: dict) -> bool:
    """Whether a later bot comment settles this claim, as the observer reads it."""
    if (comment.get("user") or {}).get("login") != BOT_LOGIN:
        return False
    if comment.get("id") == claim["comment_id"]:
        return False
    created = _parse_time(comment.get("created_at"))
    if claim["created_at"] and created and created <= claim["created_at"]:
        return False
    body = str(comment.get("body") or "")
    if body.startswith(_BOUND_RELEASE_PREFIXES):
        if _names_lease(comment, claim):
            return True
        run = _GOVERNOR_RUN.search(body)
        return bool(
            body.startswith(_BOUND_RELEASE_PREFIXES[0])
            and run
            and int(run.group(1)) == claim["run_id"]
        )
    return _is_settlement(body) or _names_lease(comment, claim)


def _is_parked_lease_receipt(body: str) -> bool:
    match = _RECEIPT_JSON.search(body)
    try:
        receipt = json.loads(match.group(1)) if match else None
    except ValueError:
        return False
    return isinstance(receipt, dict) and receipt.get("reason") == PARKED_LEASE_REASON


def _recovery_count(comments: Iterable[dict]) -> int:
    # A parked-lease receipt requeues nothing, so it spends none of the budget.
    return sum(
        1
        for c in comments
        if (c.get("user") or {}).get("login") == BOT_LOGIN
        and str(c.get("body") or "").startswith(RECOVERY_PREFIX)
        and not _is_parked_lease_receipt(str(c.get("body") or ""))
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
                index[issue] = {
                    "number": int(pr["number"]),
                    "merged": merged,
                    "state": state,
                }
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
        "schema": RECOVERY_SCHEMA,
        "issue_number": number,
        "action": "keep",
        "reason": None,
        "target": None,
        "lease_id": None,
        "lease_comment_id": None,
        "run_id": None,
        "run_status": None,
        "lease_age_seconds": None,
        "recoveries_before": _recovery_count(comments),
        "durable_pr": None if durable_pr is None else durable_pr["number"],
        "labels": sorted(labels),
    }
    if str(issue.get("state") or "OPEN").upper() != "OPEN" or RUNNING not in labels:
        decision["reason"] = "not_running"
        return decision

    if labels & PARKED:
        decision.update(
            action="recover", reason="running_label_beside_parked_state", target=None
        )
        return decision

    claim = _latest_claim(comments, repository=repository, number=number)
    if claim is not None:
        decision.update(
            lease_id=claim["lease_id"],
            lease_comment_id=claim["comment_id"],
            run_id=claim["run_id"],
        )
        if claim["created_at"] is not None:
            decision["lease_age_seconds"] = int(
                (now - claim["created_at"]).total_seconds()
            )
        if _settled_after(comments, claim):
            decision.update(action="recover", reason="settled_without_label_release")
        else:
            status = run_status(claim["run_id"])
            decision["run_status"] = status
            if status in {"completed", "missing"}:
                decision.update(
                    action="recover", reason="worker_run_terminated_without_settlement"
                )
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


def classify_stranded_validation(
    issue: dict,
    comments: list[dict],
    *,
    repository: str,
    run_status: Callable[[int], str],
    run_conclusion: Callable[[int], str],
    durable_pr: dict | None,
    now: datetime,
) -> dict:
    """Decide, without mutating anything, whether an oc-validating issue is stranded.

    Stranded means all of: the issue is open and its only state label is
    oc-validating (no gate, hold or other state, as the hosted checker itself
    requires); no merged integration PR exists for it; the newest authenticated
    claim's controller run has completed with a definite unsuccessful
    conclusion. The hosted checker refuses any worker run that did not succeed,
    so that PR can never be validated and nothing else would ever move the issue.
    """
    number = int(issue["number"])
    labels = _labels(issue)
    decision: dict[str, Any] = {
        "schema": RECOVERY_SCHEMA,
        "issue_number": number,
        "action": "keep",
        "reason": None,
        "target": None,
        "lease_id": None,
        "lease_comment_id": None,
        "run_id": None,
        "run_status": None,
        "run_conclusion": None,
        "lease_age_seconds": None,
        "recoveries_before": _recovery_count(comments),
        "durable_pr": None if durable_pr is None else durable_pr["number"],
        "stranded_pr": None,
        "labels": sorted(labels),
    }
    if (
        str(issue.get("state") or "OPEN").upper() != "OPEN"
        or VALIDATING not in labels
        or labels & (PARKED | {RUNNING, QUEUED, "oc-repair"}) != {VALIDATING}
    ):
        decision["reason"] = "not_exclusively_validating"
        return decision
    if durable_pr is not None and (
        durable_pr.get("merged") or str(durable_pr.get("state") or "").upper() != "OPEN"
    ):
        decision["reason"] = "integration_pr_merged"
        return decision
    claim = _latest_claim(comments, repository=repository, number=number)
    if claim is None:
        decision["reason"] = "no_authenticated_claim"
        return decision
    decision.update(
        lease_id=claim["lease_id"],
        lease_comment_id=claim["comment_id"],
        run_id=claim["run_id"],
    )
    if claim["created_at"] is not None:
        decision["lease_age_seconds"] = int((now - claim["created_at"]).total_seconds())
    status = run_status(claim["run_id"])
    decision["run_status"] = status
    if status != "completed":
        decision["reason"] = "worker_run_active_or_unknown"
        return decision
    conclusion = run_conclusion(claim["run_id"])
    decision["run_conclusion"] = conclusion
    if conclusion not in UNSUCCESSFUL_CONCLUSIONS:
        decision["reason"] = "worker_run_not_definitely_unsuccessful"
        return decision
    # No open PR (for example, a previous recovery closed it but could not
    # relabel) is equally stranded: there is nothing left to validate.
    decision.update(
        action="recover",
        reason=STRANDED_REASON,
        stranded_pr=None if durable_pr is None else durable_pr["number"],
    )
    if decision["recoveries_before"] < MAX_AUTOMATIC_RECOVERIES:
        decision["target"] = QUEUED
    else:
        decision["target"] = BLOCKED
        decision["reason"] = f"{STRANDED_REASON}:automatic_recoveries_exhausted"
    return decision


def _is_legacy_claim(comment: dict) -> bool:
    """A bot claim receipt written before ``oc.swarm-claim.v1`` (before 2026-09-12).

    Those receipts carry only reads, writes and dependencies: no schema, issue
    number or lease id. No lease id means nothing here can name or release the
    lease, so the parked path leaves them to the health observer instead of
    failing every wave that scans an old parked issue (#1264 has 60+). A
    receipt that claims the current schema but is malformed still fails closed.
    """
    if (comment.get("user") or {}).get("login") != BOT_LOGIN:
        return False
    match = _CLAIM.match(str(comment.get("body") or ""))
    if not match:
        return False
    try:
        claim = json.loads(match.group(1))
    except ValueError:
        return False
    return (
        isinstance(claim, dict)
        and "schema" not in claim
        and "lease_id" not in claim
        and "issue_number" not in claim
    )


def classify_parked_leases(
    issue: dict,
    comments: list[dict],
    *,
    repository: str,
    run_status: Callable[[int], str],
    now: datetime,
) -> list[dict]:
    """Decide, without mutating anything, which leases on a parked issue to release.

    A lease is unsettled when no later bot receipt settles it as the health
    observer reads receipts: a generic settlement settles every earlier claim,
    while a governor denial or worker disposition settles only the claim it
    names.
    Unsettled leases are released only together, and only when every one of
    their runs has completed or no longer exists, so the receipt can never hide
    a lease whose run is still live or unreadable.
    """
    number = int(issue["number"])
    labels = _labels(issue)
    if (
        str(issue.get("state") or "OPEN").upper() != "OPEN"
        or RUNNING in labels
        or not labels & set(LEASE_PARKED)
    ):
        return []
    unsettled = [
        claim
        for claim in _claims(
            [comment for comment in comments if not _is_legacy_claim(comment)],
            repository=repository,
            number=number,
        )
        if not any(_settles_parked_claim(comment, claim) for comment in comments)
    ]
    statuses = {claim["run_id"]: run_status(claim["run_id"]) for claim in unsettled}
    if any(status not in {"completed", "missing"} for status in statuses.values()):
        return []
    return [
        {
            "schema": RECOVERY_SCHEMA,
            "issue_number": number,
            "action": "recover",
            "reason": PARKED_LEASE_REASON,
            "target": None,
            "lease_id": claim["lease_id"],
            "lease_comment_id": claim["comment_id"],
            "run_id": claim["run_id"],
            "run_status": statuses[claim["run_id"]],
            "lease_age_seconds": int((now - claim["created_at"]).total_seconds()),
            "recoveries_before": _recovery_count(comments),
            "durable_pr": None,
            "labels": sorted(labels),
        }
        for claim in unsettled
    ]


def parked_scan_window(numbers: Iterable[int], run_id: int) -> list[int]:
    """The parked issues this wave reads: a window chosen by the run id."""
    ordered = sorted(set(numbers))
    if len(ordered) <= PARKED_SCAN_PER_WAVE:
        return ordered
    start = run_id % len(ordered)
    return [ordered[(start + i) % len(ordered)] for i in range(PARKED_SCAN_PER_WAVE)]


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
            ["gh", *args],
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        text = result.stdout.strip()
        return json.loads(text) if text.startswith(("{", "[")) else None

    def _paged(
        self, path: str, *, page_budget=10, require_complete=False
    ) -> list[dict]:
        rows: list[dict] = []
        for page in range(1, page_budget + 1):
            batch = self._run(
                ["api", f"repos/{self.repository}/{path}?per_page=100&page={page}"]
            )
            if not isinstance(batch, list):
                if require_complete:
                    raise ValueError("comment_history_unconfirmed")
                break
            rows.extend(batch)
            if len(batch) < 100:
                return rows
        if require_complete:
            raise ValueError("comment_history_incomplete")
        return rows

    def running_issues(self) -> list[dict]:
        rows = self._run(
            [
                "issue",
                "list",
                "--repo",
                self.repository,
                "--state",
                "open",
                "--label",
                RUNNING,
                "--limit",
                "200",
                "--json",
                "number,title,body,state,labels,updatedAt",
            ]
        )
        return list(rows or [])

    def validating_issues(self) -> list[dict]:
        rows = self._run(
            [
                "issue",
                "list",
                "--repo",
                self.repository,
                "--state",
                "open",
                "--label",
                VALIDATING,
                "--limit",
                "200",
                "--json",
                "number,title,body,state,labels,updatedAt",
            ]
        )
        return list(rows or [])

    def parked_issues(self) -> list[dict]:
        rows: list[dict] = []
        for label in LEASE_PARKED:
            rows += list(
                self._run(
                    [
                        "issue",
                        "list",
                        "--repo",
                        self.repository,
                        "--state",
                        "open",
                        "--label",
                        label,
                        "--limit",
                        "200",
                        "--json",
                        "number,state,labels",
                    ]
                )
                or []
            )
        return rows

    def pull_requests(self) -> list[dict]:
        rows = self._run(
            [
                "pr",
                "list",
                "--repo",
                self.repository,
                "--state",
                "all",
                "--base",
                "oc-autonomous-integration",
                "--limit",
                "200",
                "--json",
                "number,state,body,mergedAt",
            ]
        )
        return list(rows or [])

    def comments(self, number: int) -> list[dict]:
        return self._paged(
            f"issues/{number}/comments", page_budget=100, require_complete=True
        )

    def labeled_at(self, number: int) -> datetime | None:
        latest = None
        for event in self._paged(f"issues/{number}/timeline"):
            if (
                event.get("event") != "labeled"
                or (event.get("label") or {}).get("name") != RUNNING
            ):
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

    def run_conclusion(self, run_id: int) -> str:
        try:
            run = self._run(["api", f"repos/{self.repository}/actions/runs/{run_id}"])
        except (OSError, subprocess.SubprocessError, ValueError):
            return "unknown"
        return str((run or {}).get("conclusion") or "unknown")

    def issue(self, number: int) -> dict:
        return self._run(
            [
                "issue",
                "view",
                str(number),
                "--repo",
                self.repository,
                "--json",
                "number,title,body,state,labels",
            ]
        )

    def edit_labels(self, number: int, *, remove: list[str], add: list[str]) -> None:
        args = ["issue", "edit", str(number), "--repo", self.repository]
        for label in remove:
            args += ["--remove-label", label]
        for label in add:
            args += ["--add-label", label]
        self._run(args)

    def comment(self, number: int, body: str) -> dict:
        return (
            self._run(
                [
                    "api",
                    "--method",
                    "POST",
                    f"repos/{self.repository}/issues/{number}/comments",
                    "--input",
                    "-",
                ],
                {"body": body},
            )
            or {}
        )


def apply_recovery(
    transport: GitHubTransport, decision: dict, *, controller_run_url: str
) -> dict:
    """Release one stale lease and write its durable recovery receipt."""
    number = decision["issue_number"]
    present = set(decision.get("labels") or [RUNNING])
    remove = [RUNNING]
    add = []
    if decision["target"] == QUEUED:
        add = [QUEUED]
    elif decision["target"] in (VALIDATING, BLOCKED):
        remove.append(QUEUED)
        add = [decision["target"]]
    # Only touch labels that are actually present; never edit unrelated labels.
    remove = [label for label in remove if label in present]
    add = [label for label in add if label not in present]
    transport.edit_labels(number, remove=remove, add=add)
    current = transport.issue(number)
    if RUNNING in _labels(current):
        raise ValueError("stale lease release unconfirmed")
    receipt = {k: v for k, v in decision.items() if k != "action"}
    receipt["released_state"] = sorted(_labels(current))
    body = (
        RECOVERY_PREFIX
        + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        + f"`. Controller run: {controller_run_url}."
    )
    saved = transport.comment(number, body)
    if saved.get("body") != body or not saved.get("id"):
        raise ValueError("recovery receipt unconfirmed")
    return {**decision, "recovery_comment_id": saved["id"]}


def apply_stranded_recovery(
    transport: GitHubTransport, decision: dict, *, controller_run_url: str
) -> dict:
    """Requeue (or park) a stranded issue and receipt it on the issue.

    The PR is deliberately left open and only named in the receipt: the plan
    job that runs this reconciler has read-only pull-request access, and the
    next worker opens a new PR on its own branch, which the completion lane
    selects as the newest open PR for the issue. Only issue writes happen here.
    """
    number = decision["issue_number"]
    present = set(decision.get("labels") or [VALIDATING])
    remove = [label for label in (VALIDATING, QUEUED) if label in present]
    add = [decision["target"]] if decision["target"] not in present else []
    if decision["target"] == QUEUED:
        remove = [label for label in remove if label != QUEUED]
    transport.edit_labels(number, remove=remove, add=add)
    current = transport.issue(number)
    labels = _labels(current)
    if VALIDATING in labels or RUNNING in labels or decision["target"] not in labels:
        raise ValueError("stranded validation release unconfirmed")
    receipt = {k: v for k, v in decision.items() if k != "action"}
    receipt["released_state"] = sorted(labels)
    body = (
        RECOVERY_PREFIX
        + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        + f"`. Controller run: {controller_run_url}."
    )
    saved = transport.comment(number, body)
    if saved.get("body") != body or not saved.get("id"):
        raise ValueError("recovery receipt unconfirmed")
    return {**decision, "recovery_comment_id": saved["id"]}


def apply_parked_recovery(
    transport: GitHubTransport, decision: dict, *, controller_run_url: str
) -> dict:
    """Receipt one released lease on a parked issue; labels are left as they are."""
    number = decision["issue_number"]
    current = transport.issue(number)
    labels = _labels(current)
    if (
        str(current.get("state") or "OPEN").upper() != "OPEN"
        or RUNNING in labels
        or not labels & set(LEASE_PARKED)
    ):
        raise ValueError("parked state changed before release")
    receipt = {k: v for k, v in decision.items() if k != "action"}
    receipt["released_state"] = sorted(labels)
    body = (
        RECOVERY_PREFIX
        + json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        + f"`. Controller run: {controller_run_url}."
    )
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
    controller_run_url = (
        f"https://github.com/{transport.repository}/actions/runs/{run_id}"
    )
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
                issue,
                comments,
                repository=transport.repository,
                run_status=transport.run_status,
                labeled_at=transport.labeled_at(number),
                durable_pr=durable.get(number),
                now=now,
            )
            if decision["action"] != "recover":
                kept.append(decision)
                continue
            if dry_run:
                recovered.append({**decision, "dry_run": True})
                continue
            recovered.append(
                apply_recovery(
                    transport, decision, controller_run_url=controller_run_url
                )
            )
        except (
            OSError,
            subprocess.SubprocessError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            # Never expose issue text or raw API errors; never retry a write blindly.
            errors.append(
                {
                    "issue": number,
                    "reason": "lease_reconcile_unconfirmed",
                    "error_type": type(exc).__name__,
                }
            )
    stranded: list[dict] = []
    handled = {int(i["number"]) for i in running}
    validating = transport.validating_issues()
    for issue in validating:
        number = int(issue["number"])
        if number in handled:
            continue
        try:
            comments = transport.comments(number)
            decision = classify_stranded_validation(
                issue,
                comments,
                repository=transport.repository,
                run_status=transport.run_status,
                run_conclusion=transport.run_conclusion,
                durable_pr=durable.get(number),
                now=now,
            )
            if decision["action"] != "recover":
                continue
            if dry_run:
                stranded.append({**decision, "dry_run": True})
                continue
            stranded.append(
                apply_stranded_recovery(
                    transport, decision, controller_run_url=controller_run_url
                )
            )
        except (
            OSError,
            subprocess.SubprocessError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            errors.append(
                {
                    "issue": number,
                    "reason": "stranded_validation_unconfirmed",
                    "error_type": type(exc).__name__,
                }
            )
    parked: list[dict] = []
    handled |= {int(i["number"]) for i in validating}
    candidates = {
        int(i["number"])
        for i in transport.parked_issues()
        if int(i["number"]) not in handled
    }
    for number in parked_scan_window(candidates, run_id):
        try:
            decisions = classify_parked_leases(
                transport.issue(number),
                transport.comments(number),
                repository=transport.repository,
                run_status=transport.run_status,
                now=now,
            )
            for decision in decisions:
                if dry_run:
                    parked.append({**decision, "dry_run": True})
                    continue
                parked.append(
                    apply_parked_recovery(
                        transport, decision, controller_run_url=controller_run_url
                    )
                )
        except (
            OSError,
            subprocess.SubprocessError,
            ValueError,
            TypeError,
            KeyError,
        ) as exc:
            errors.append(
                {
                    "issue": number,
                    "reason": "parked_lease_unconfirmed",
                    "error_type": type(exc).__name__,
                }
            )
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "running_count": len(running),
        "recovered_count": len(recovered),
        "running_after": len(running) - len(recovered),
        "recovered": recovered,
        "kept": kept,
        "stranded_recovered_count": len(stranded),
        "stranded_recovered": stranded,
        "parked_lease_recovered_count": len(parked),
        "parked_lease_recovered": parked,
        "errors": errors,
        "dry_run": dry_run,
        "safety": {
            "provider_calls": False,
            "repository_writes": False,
            "time_alone_releases_lease": False,
            "max_automatic_recoveries": MAX_AUTOMATIC_RECOVERIES,
            "manual_lease_max_age_seconds": MANUAL_LEASE_MAX_AGE_SECONDS,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--github-output")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    report = reconcile(
        GitHubTransport(args.repository), run_id=args.run_id, dry_run=args.dry_run
    )
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"recovered_count={report['recovered_count']}\n")
            handle.write(f"running_after={report['running_after']}\n")
            handle.write(
                f"stranded_recovered_count={report['stranded_recovered_count']}\n"
            )
            handle.write(
                "parked_lease_recovered_count="
                f"{report['parked_lease_recovered_count']}\n"
            )
            handle.write(f"reconcile_errors={len(report['errors'])}\n")
    json.dump(report, sys.stdout, sort_keys=True, default=str)
    sys.stdout.write("\n")
    # Recovery errors are evidence for the observer, not a reason to stop the wave.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
