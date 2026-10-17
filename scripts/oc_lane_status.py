#!/usr/bin/env python3
"""Publish one durable lane-status record per controller wave.

The planner already classifies every wave (``homeostasis``: status, reason and
evidence), but that reason reached only the run's step summary: 32 consecutive
zero-launch waves left no durable reason anywhere a person or Mission Control
could read. This writes it to the lane-status feed issue (#1949):

* one bot comment tagged ``OC-LANE-STATUS-CURRENT-V1`` is updated in place with
  the latest wave, so the current state is always one read away;
* a comment tagged ``OC-LANE-STATUS-TRANSITION-V1`` is appended only when the
  lane state or reason changes, so history is durable without a comment per
  wave.

Lane states are ``working``, ``idle``, ``blocked``, ``failed`` and
``recovering``. Only the workflow bot's own comments are read back. Nothing here
calls a provider or writes a repository file, and publishing is best effort: a
failure is reported in the output, never raised into the wave.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "oc.lane-status.v1"
STATUS_ISSUE = 1949
CURRENT_TAG = "OC-LANE-STATUS-CURRENT-V1"
TRANSITION_TAG = "OC-LANE-STATUS-TRANSITION-V1"
BOT_LOGIN = "github-actions[bot]"
LANE_STATES = ("working", "idle", "blocked", "failed", "recovering")

#: Planner homeostasis reason -> lane state (oc_swarm_controller.HOMEOSTASIS_STATUS).
_REASON_STATE = {
    "executing": "working",
    "capacity_full": "working",
    "queue_empty": "idle",
    "gated_only": "blocked",
    "dependency_blocked": "blocked",
    "lane_refused": "blocked",
    "lock_contended": "blocked",
    "held_other": "blocked",
    "invariant_violation": "failed",
}


def _int(value: Any) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _held_count(homeostasis: dict) -> int:
    held = (homeostasis.get("evidence") or {}).get("unfinished_held")
    if not isinstance(held, dict):
        return 0
    return sum(_int(value) for value in held.values())


def lane_state(
    homeostasis: dict | None,
    *,
    launched: int,
    recovered: int,
    reconcile_errors: int,
    provider_blocked: bool,
) -> tuple[str, str]:
    """(lane state, reason) for one wave. Missing planner output is a failure."""
    if not isinstance(homeostasis, dict) or not homeostasis.get("reason"):
        return "failed", "plan_output_missing"
    reason = str(homeostasis["reason"])
    if recovered > 0:
        return "recovering", f"lease_recovered:{reason}"
    if reconcile_errors > 0:
        return "failed", f"lease_reconcile_errors:{reason}"
    if launched > 0:
        return "working", reason
    if provider_blocked and reason in {"executing", "capacity_full"}:
        # Planned paid work that the governor or NO-API mode refused to launch.
        return "blocked", f"provider_blocked:{reason}"
    if reason == "executing":
        # The plan selected work but nothing launched (claim failed or confirmed
        # no claims): never report that as working.
        return "blocked", "selected_not_launched"
    if reason == "queue_empty" and _held_count(homeostasis) > 0:
        # Nothing is queued, but unfinished work exists and every issue of it is
        # held (repair pending, validating, backoff, gates): that is not idle.
        return "blocked", "queue_empty_unfinished_held"
    return _REASON_STATE.get(reason, "blocked"), reason


def build_record(
    plan: dict | None,
    recovery: dict | None,
    *,
    run_id: str,
    run_url: str,
    event: str,
    provider_launch_count: Any,
    provider_free_launch_count: Any,
    provider_blocked: bool,
    now: datetime | None = None,
) -> dict:
    plan = plan if isinstance(plan, dict) else {}
    recovery = recovery if isinstance(recovery, dict) else {}
    homeostasis = plan.get("homeostasis")
    paid = _int(provider_launch_count)
    free = _int(provider_free_launch_count)
    recovered = _int(recovery.get("recovered_count")) + _int(
        recovery.get("stranded_recovered_count")
    )
    errors = recovery.get("errors")
    reconcile_errors = len(errors) if isinstance(errors, list) else 0
    state, reason = lane_state(
        homeostasis,
        launched=paid + free,
        recovered=recovered,
        reconcile_errors=reconcile_errors,
        provider_blocked=provider_blocked,
    )
    evidence = (
        (homeostasis or {}).get("evidence") if isinstance(homeostasis, dict) else None
    )
    return {
        "schema": SCHEMA,
        "lane_state": state,
        "reason": reason,
        "homeostasis_status": (homeostasis or {}).get("status")
        if isinstance(homeostasis, dict)
        else None,
        "homeostasis_reason": (homeostasis or {}).get("reason")
        if isinstance(homeostasis, dict)
        else None,
        "launched": {"provider": paid, "provider_free": free},
        "provider_blocked": bool(provider_blocked),
        "leases_recovered": recovered,
        "lease_reconcile_errors": reconcile_errors,
        "selected": sorted(_int(n) for n in plan.get("selected_numbers") or []),
        "evidence": evidence if isinstance(evidence, dict) else {},
        "run_id": str(run_id),
        "run_url": run_url,
        "event": event,
        "generated_at": (now or datetime.now(timezone.utc))
        .isoformat()
        .replace("+00:00", "Z"),
    }


def render(tag: str, record: dict) -> str:
    head = (
        f"Lane **{record['lane_state']}**, reason `{record['reason']}`, "
        f"controller run {record['run_url']}"
    )
    return f"<!-- {tag}\n{json.dumps(record, sort_keys=True)}\n-->\n{head}"


def parse(body: str, tag: str) -> dict | None:
    match = re.match(
        r"<!-- " + re.escape(tag) + r"\n(?P<json>\{.*?\})\n-->", body or "", re.DOTALL
    )
    if not match:
        return None
    try:
        record = json.loads(match.group("json"))
    except ValueError:
        return None
    return (
        record if isinstance(record, dict) and record.get("schema") == SCHEMA else None
    )


def plan_writes(comments: list[dict], record: dict) -> dict:
    """Which writes publish ``record``: patch or create CURRENT, maybe a TRANSITION."""
    current = None
    for comment in comments:
        if (comment.get("user") or {}).get("login") != BOT_LOGIN:
            continue
        if parse(comment.get("body") or "", CURRENT_TAG) is None:
            continue
        if current is None or int(comment["id"]) > int(current["id"]):
            current = comment
    previous = parse(current["body"], CURRENT_TAG) if current else None
    changed = previous is None or (
        previous.get("lane_state"),
        previous.get("reason"),
    ) != (record["lane_state"], record["reason"])
    return {
        "current_comment_id": current["id"] if current else None,
        "transition": changed,
        "previous": None
        if previous is None
        else {
            "lane_state": previous.get("lane_state"),
            "reason": previous.get("reason"),
        },
    }


class GitHub:
    def __init__(self, repository: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("invalid repository")
        self.repository = repository

    def _api(self, path: str, payload: dict | None = None, method: str = "GET") -> Any:
        args = ["gh", "api", "--method", method, f"repos/{self.repository}/{path}"]
        if payload is not None:
            args += ["--input", "-"]
        result = subprocess.run(
            args,
            input=json.dumps(payload) if payload is not None else None,
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        return json.loads(result.stdout) if result.stdout.strip() else None

    def comments(self, issue: int) -> list[dict]:
        """Oldest-first comments up to and including the page holding CURRENT.

        CURRENT is created first and then only updated in place, so it sits on
        the first page; transitions accumulate after it. Stopping at the page
        that holds it keeps each wave to one read however long history grows.
        """
        rows: list[dict] = []
        for page in range(1, 11):
            batch = self._api(f"issues/{issue}/comments?per_page=100&page={page}")
            if not isinstance(batch, list):
                raise TypeError("status_comments_unreadable")
            rows.extend(batch)
            if len(batch) < 100 or any(
                (row.get("user") or {}).get("login") == BOT_LOGIN
                and parse(row.get("body") or "", CURRENT_TAG) is not None
                for row in batch
            ):
                return rows
        raise ValueError("status_comments_truncated")

    def create(self, issue: int, body: str) -> int:
        saved = self._api(f"issues/{issue}/comments", {"body": body}, "POST")
        if (saved or {}).get("body") != body:
            raise ValueError("status_comment_unconfirmed")
        return int(saved["id"])

    def update(self, comment_id: int, body: str) -> None:
        saved = self._api(f"issues/comments/{comment_id}", {"body": body}, "PATCH")
        if (saved or {}).get("body") != body:
            raise ValueError("status_comment_unconfirmed")


def publish(github: GitHub, issue: int, record: dict, *, dry_run: bool = False) -> dict:
    writes = plan_writes(github.comments(issue), record)
    result = {"record": record, **writes, "dry_run": dry_run}
    if dry_run:
        return result
    body = render(CURRENT_TAG, record)
    if writes["current_comment_id"] is None:
        result["current_comment_id"] = github.create(issue, body)
    else:
        github.update(int(writes["current_comment_id"]), body)
    if writes["transition"]:
        result["transition_comment_id"] = github.create(
            issue, render(TRANSITION_TAG, record)
        )
    return result


def _load(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--plan")
    parser.add_argument("--lease-recovery")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--event", default="")
    parser.add_argument("--provider-launch-count", default="0")
    parser.add_argument("--provider-free-launch-count", default="0")
    parser.add_argument("--provider-blocked", default="false")
    parser.add_argument("--status-issue", type=int, default=STATUS_ISSUE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    record = build_record(
        _load(args.plan),
        _load(args.lease_recovery),
        run_id=args.run_id,
        run_url=args.run_url,
        event=args.event,
        provider_launch_count=args.provider_launch_count,
        provider_free_launch_count=args.provider_free_launch_count,
        provider_blocked=str(args.provider_blocked).lower() == "true",
    )
    try:
        report = publish(
            GitHub(args.repository), args.status_issue, record, dry_run=args.dry_run
        )
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        report = {"record": record, "error": type(exc).__name__}
    json.dump(report, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    # Telemetry never stops a wave.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
