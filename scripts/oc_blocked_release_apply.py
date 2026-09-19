"""Apply an authorized blocked-work release plan with durable replay receipts.

This is the deliberately separate mutation half of ``oc_blocked_reconcile``.
The reconciler proves that a blocker cleared and emits a bounded plan. This
module re-observes the exact issue immediately before changing labels, refuses
owner-gated work, preserves unrelated labels, verifies the write, and persists
an idempotency receipt. It never calls a model provider, merges, deploys, or
changes repository files.

The CLI is dry-run by default. ``--apply`` is an explicit caller decision; the
hosted workflow is intentionally not wired here because that protected change
remains owner-gated.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

PLAN_SCHEMA = "oc.blocked-release-plan.v1"
RECEIPT_SCHEMA = "oc.blocked-release-receipt.v1"
BLOCKED = "oc-blocked"
QUEUED = "oc-queued"
OWNER_GATES = frozenset({"oc-owner-gate", "blocked-on-owner"})
RECEIPT_PREFIX = "[OC-RUNTIME] Blocked work released: `"
MAX_ACTIONS = 100


def _labels(issue: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for label in issue.get("labels") or []:
        name = label if isinstance(label, str) else label.get("name")
        if name:
            names.add(str(name))
    return names


class GitHubTransport:
    """Minimal GitHub transport; arguments never pass through a shell."""

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

    def issue(self, number: int) -> dict[str, Any]:
        return self._run(
            [
                "issue",
                "view",
                str(number),
                "--repo",
                self.repository,
                "--json",
                "number,title,body,state,labels,url",
            ]
        )

    def edit_labels(self, number: int, *, remove: list[str], add: list[str]) -> None:
        args = ["issue", "edit", str(number), "--repo", self.repository]
        for label in remove:
            args += ["--remove-label", label]
        for label in add:
            args += ["--add-label", label]
        self._run(args)

    def comments(self, number: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for page in range(1, 11):
            batch = self._run(
                [
                    "api",
                    f"repos/{self.repository}/issues/{number}/comments?per_page=100&page={page}",
                ]
            )
            if not isinstance(batch, list):
                break
            rows.extend(batch)
            if len(batch) < 100:
                break
        return rows

    def comment(self, number: int, body: str) -> dict[str, Any]:
        return self._run(
            [
                "api",
                "--method",
                "POST",
                f"repos/{self.repository}/issues/{number}/comments",
                "--input",
                "-",
            ],
            {"body": body},
        ) or {}


def _validate_action(action: dict[str, Any]) -> None:
    number = action.get("issue_number")
    expected_key = f"blocked-release:{number}:{str(action.get('blocker') or 'unknown').lower()}"
    if (
        action.get("action") != "replace_queue_labels"
        or not isinstance(number, int)
        or number < 1
        or action.get("idempotency_key") != expected_key
        or action.get("release_authorized") is not True
        or action.get("requires_labels") != [BLOCKED]
        or action.get("remove_labels") != [BLOCKED]
        or action.get("add_labels") != [QUEUED]
        or not str(action.get("reason") or "").strip()
    ):
        raise ValueError("invalid or unauthorized release action")


def _receipt_body(
    *,
    repository: str,
    action: dict[str, Any],
    before: set[str],
    after: set[str],
    controller_run_url: str,
) -> tuple[str, dict[str, Any]]:
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "repository": repository,
        "issue_number": action["issue_number"],
        "idempotency_key": action["idempotency_key"],
        "blocker": action.get("blocker"),
        "before_labels": sorted(before),
        "after_labels": sorted(after),
        "controller_run_url": controller_run_url,
        "provider_calls": 0,
    }
    body = RECEIPT_PREFIX + json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "`."
    return body, receipt


def _existing_receipt(
    comments: list[dict[str, Any]],
    *,
    repository: str,
    number: int,
    idempotency_key: str,
    body: str | None = None,
) -> dict[str, Any] | None:
    for comment in comments:
        raw = str(comment.get("body") or "")
        if body is not None and raw == body and comment.get("id"):
            return comment
        if not raw.startswith(RECEIPT_PREFIX) or not raw.endswith("`."):
            continue
        try:
            record = json.loads(raw[len(RECEIPT_PREFIX) : -2])
        except (TypeError, ValueError):
            continue
        if (
            record.get("schema") == RECEIPT_SCHEMA
            and record.get("repository") == repository
            and record.get("issue_number") == number
            and record.get("idempotency_key") == idempotency_key
            and comment.get("id")
        ):
            return comment
    return None


def apply_action(
    transport: GitHubTransport,
    action: dict[str, Any],
    *,
    controller_run_url: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Apply one release after an exact current-state check."""
    _validate_action(action)
    number = action["issue_number"]
    current = transport.issue(number)
    if current.get("number") != number or str(current.get("state") or "").upper() != "OPEN":
        raise ValueError("issue identity or state changed")
    before = _labels(current)
    if before & OWNER_GATES:
        raise ValueError("owner-gated issue cannot be released")

    expected_after = (before - {BLOCKED}) | {QUEUED}
    body, receipt = _receipt_body(
        repository=transport.repository,
        action=action,
        before=before,
        after=expected_after,
        controller_run_url=controller_run_url,
    )

    if BLOCKED not in before:
        existing = _existing_receipt(
            transport.comments(number),
            repository=transport.repository,
            number=number,
            idempotency_key=action["idempotency_key"],
        )
        if QUEUED in before and existing:
            return {
                "issue_number": number,
                "outcome": "already_applied",
                "receipt_comment_id": existing["id"],
                "idempotency_key": action["idempotency_key"],
            }
        raise ValueError("release precondition absent and receipt unconfirmed")

    if dry_run:
        return {
            "issue_number": number,
            "outcome": "dry_run",
            "idempotency_key": action["idempotency_key"],
            "before_labels": sorted(before),
            "after_labels": sorted(expected_after),
        }

    try:
        transport.edit_labels(number, remove=[BLOCKED], add=[QUEUED])
    except (OSError, subprocess.SubprocessError):
        # A transport failure can follow a successful write. Observe before
        # deciding whether to stop; never blindly repeat a mutation.
        pass
    changed = transport.issue(number)
    if changed.get("number") != number or str(changed.get("state") or "").upper() != "OPEN":
        raise ValueError("release write identity changed")
    if _labels(changed) != expected_after:
        raise ValueError("release label transition unconfirmed")

    try:
        saved = transport.comment(number, body)
    except (OSError, subprocess.SubprocessError):
        saved = _existing_receipt(
            transport.comments(number),
            repository=transport.repository,
            number=number,
            idempotency_key=action["idempotency_key"],
            body=body,
        ) or {}
    if saved.get("body") != body or not saved.get("id"):
        raise ValueError("release receipt unconfirmed")
    return {
        "issue_number": number,
        "outcome": "applied",
        "receipt_comment_id": saved["id"],
        "idempotency_key": action["idempotency_key"],
        "receipt": receipt,
    }


def apply_plan(
    transport: GitHubTransport,
    plan: dict[str, Any],
    *,
    controller_run_url: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Apply a bounded plan, isolating one issue failure from the next."""
    actions = list(plan.get("actions") or [])
    if plan.get("schema") != PLAN_SCHEMA or plan.get("mutates") is not False:
        raise ValueError("invalid release plan")
    if plan.get("action_count") != len(actions) or len(actions) > MAX_ACTIONS:
        raise ValueError("release plan is not bounded")
    numbers = [action.get("issue_number") for action in actions]
    keys = [action.get("idempotency_key") for action in actions]
    if len(set(numbers)) != len(numbers) or len(set(keys)) != len(keys):
        raise ValueError("duplicate release action")
    for action in actions:
        _validate_action(action)

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for action in actions:
        try:
            results.append(
                apply_action(
                    transport,
                    action,
                    controller_run_url=controller_run_url,
                    dry_run=dry_run,
                )
            )
        except (OSError, subprocess.SubprocessError, TypeError, ValueError, KeyError) as exc:
            errors.append(
                {
                    "issue_number": action.get("issue_number"),
                    "reason": "release_unconfirmed",
                    "error_type": type(exc).__name__,
                }
            )
    return {
        "schema": "oc.blocked-release-apply-report.v1",
        "repository": transport.repository,
        "planned_count": len(actions),
        "applied_count": sum(row["outcome"] == "applied" for row in results),
        "already_applied_count": sum(row["outcome"] == "already_applied" for row in results),
        "dry_run_count": sum(row["outcome"] == "dry_run" for row in results),
        "results": results,
        "errors": errors,
        "dry_run": dry_run,
        "safety": {
            "provider_calls": False,
            "merge": False,
            "deploy": False,
            "owner_gates_preserved": True,
            "unrelated_labels_preserved": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--controller-run-url", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    with open(args.plan, encoding="utf-8") as handle:
        plan = json.load(handle)
    report = apply_plan(
        GitHubTransport(args.repository),
        plan,
        controller_run_url=args.controller_run_url,
        dry_run=not args.apply,
    )
    json.dump(report, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
