"""Persist only the GitHub facts requested by blocked-work reconciliation.

The Swarm Controller emits ``observation_requests`` when it cannot prove that a
blocker remains or cleared. This provider-free helper fulfills that bounded
shopping list and returns a replayable snapshot. It reads GitHub but never
changes issues, pull requests, workflows, deployments, or repository files.

Existing observations are reused. Re-running the same request list after an
interruption therefore performs no duplicate fetches and returns the same
snapshot. The hosted workflow is intentionally not changed here.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from copy import deepcopy
from typing import Any

SCHEMA = "oc.blocked-snapshot-enrichment.v1"
ALLOWED_KINDS = frozenset({"issue_comments", "issue_state", "pull_request_state"})
MAX_REQUESTS = 200


class GitHubTransport:
    """Minimal read-only GitHub transport; arguments never pass through a shell."""

    def __init__(self, repository: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("invalid repository")
        self.repository = repository

    def _run(self, args: list[str]) -> Any:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        text = result.stdout.strip()
        return json.loads(text) if text.startswith(("{", "[")) else None

    def issue_comments(self, number: int) -> list[dict[str, Any]]:
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

    def issue(self, number: int) -> dict[str, Any]:
        return self._run(
            [
                "issue",
                "view",
                str(number),
                "--repo",
                self.repository,
                "--json",
                "number,state,url",
            ]
        )

    def pull_request(self, number: int) -> dict[str, Any]:
        return self._run(
            [
                "pr",
                "view",
                str(number),
                "--repo",
                self.repository,
                "--json",
                "number,state,mergedAt,url",
            ]
        )


def _validated_requests(report: dict[str, Any]) -> list[tuple[str, int]]:
    requests = report.get("observation_requests")
    if not isinstance(requests, list) or len(requests) > MAX_REQUESTS:
        raise ValueError("observation request list is missing or unbounded")
    validated: list[tuple[str, int]] = []
    for request in requests:
        kind = request.get("kind") if isinstance(request, dict) else None
        number = request.get("number") if isinstance(request, dict) else None
        if kind not in ALLOWED_KINDS or not isinstance(number, int) or number < 1:
            raise ValueError("invalid observation request")
        validated.append((kind, number))
    if len(set(validated)) != len(validated):
        raise ValueError("duplicate observation request")
    return sorted(validated, key=lambda row: (row[0], row[1]))


def _known_issue(snapshot: dict[str, Any], number: int) -> bool:
    for issue in snapshot.get("issues") or []:
        if issue.get("number") != number:
            continue
        if str(issue.get("state") or "").upper() in {"OPEN", "CLOSED"}:
            return True
    return False


def _known_pull_request(snapshot: dict[str, Any], number: int) -> bool:
    for pull_request in snapshot.get("pull_requests") or []:
        if pull_request.get("number") != number:
            continue
        state = str(pull_request.get("state") or "").upper()
        if state in {"OPEN", "CLOSED", "MERGED"} or pull_request.get("merged_at"):
            return True
    return False


def _upsert(rows: list[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    number = record["number"]
    updated = [row for row in rows if row.get("number") != number]
    updated.append(record)
    return sorted(updated, key=lambda row: int(row.get("number") or 0))


def enrich_snapshot(
    transport: GitHubTransport,
    snapshot: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    """Fulfill a bounded request list and return a restart-stable snapshot."""
    requested = _validated_requests(report)
    existing_repository = snapshot.get("repository")
    if existing_repository is not None and existing_repository != transport.repository:
        raise ValueError("snapshot repository identity changed")

    enriched = deepcopy(snapshot)
    enriched["repository"] = transport.repository
    enriched.setdefault("issues", [])
    enriched.setdefault("pull_requests", [])
    enriched.setdefault("issue_comments", {})
    if not isinstance(enriched["issue_comments"], dict):
        raise TypeError("issue_comments must be a mapping")

    fetched: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for kind, number in requested:
        record = {"kind": kind, "number": number}
        try:
            if kind == "issue_comments":
                if str(number) in enriched["issue_comments"] or number in enriched["issue_comments"]:
                    reused.append(record)
                    continue
                comments = transport.issue_comments(number)
                enriched["issue_comments"][str(number)] = [
                    {
                        "id": comment.get("id"),
                        "body": str(comment.get("body") or ""),
                        "author": str((comment.get("user") or {}).get("login") or ""),
                    }
                    for comment in comments
                ]
            elif kind == "issue_state":
                if _known_issue(enriched, number):
                    reused.append(record)
                    continue
                issue = transport.issue(number)
                if issue.get("number") != number:
                    raise ValueError("issue observation identity mismatch")
                state = str(issue.get("state") or "").upper()
                if state not in {"OPEN", "CLOSED"}:
                    raise ValueError("issue observation state missing")
                enriched["issues"] = _upsert(
                    list(enriched["issues"]),
                    {"number": number, "state": state, "url": issue.get("url")},
                )
            else:
                if _known_pull_request(enriched, number):
                    reused.append(record)
                    continue
                pull_request = transport.pull_request(number)
                if pull_request.get("number") != number:
                    raise ValueError("pull request observation identity mismatch")
                state = str(pull_request.get("state") or "").upper()
                merged_at = pull_request.get("mergedAt") or pull_request.get("merged_at")
                if state not in {"OPEN", "CLOSED", "MERGED"} and not merged_at:
                    raise ValueError("pull request observation state missing")
                enriched["pull_requests"] = _upsert(
                    list(enriched["pull_requests"]),
                    {
                        "number": number,
                        "state": "MERGED" if merged_at else state,
                        "merged_at": merged_at,
                        "url": pull_request.get("url"),
                    },
                )
            fetched.append(record)
        except (OSError, subprocess.SubprocessError, TypeError, ValueError, KeyError) as exc:
            errors.append({**record, "reason": "observation_unconfirmed", "error_type": type(exc).__name__})

    enriched["blocked_enrichment"] = {
        "schema": SCHEMA,
        "repository": transport.repository,
        "requested_count": len(requested),
        "fetched": fetched,
        "reused": reused,
        "errors": errors,
        "complete": not errors,
        "provider_calls": 0,
        "mutates_github": False,
    }
    return enriched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    with open(args.snapshot, encoding="utf-8") as handle:
        snapshot = json.load(handle)
    with open(args.report, encoding="utf-8") as handle:
        report = json.load(handle)
    enriched = enrich_snapshot(GitHubTransport(args.repository), snapshot, report)
    text = json.dumps(enriched, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
