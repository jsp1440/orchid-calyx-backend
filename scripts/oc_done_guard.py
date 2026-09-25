"""Audit ``oc-done`` claims in a repository and fail them closed to ``oc-validating``.

Read-only by default; ``--apply`` performs the bounded label transitions. All
GitHub access goes through ``gh api`` with the caller's ``GH_TOKEN``.

    python scripts/oc_done_guard.py --repo jsp1440/orchid-calyx-backend [--apply] [--limit 25]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.oc_done_guard import (
    DONE_LABEL,
    FULL_SHA,
    Observation,
    decide,
    parse_receipt_comment,
    transitions,
)


def gh_api(path: str, *args: str) -> object:
    out = subprocess.run(
        ["gh", "api", path, *args], check=True, capture_output=True, text=True
    ).stdout
    return json.loads(out) if out.strip() else None


def sha_on_target(repo: str, target: str):
    cache: dict[str, bool] = {}

    def check(sha: str) -> bool:
        if not FULL_SHA.fullmatch(sha):
            return False
        if sha not in cache:
            try:
                compare = gh_api(f"repos/{repo}/compare/{target}...{sha}")
                cache[sha] = isinstance(compare, dict) and compare.get("status") in {
                    "identical",
                    "behind",
                }
            except subprocess.CalledProcessError:
                cache[sha] = False
        return cache[sha]

    return check


def observe(repo: str, issue: dict) -> Observation:
    number = int(issue["number"])
    comments = gh_api(f"repos/{repo}/issues/{number}/comments", "--paginate") or []
    receipts = tuple(
        r for r in (parse_receipt_comment(c.get("body", "")) for c in comments) if r
    )
    merged: list[str] = []
    timeline = gh_api(f"repos/{repo}/issues/{number}/timeline", "--paginate") or []
    for event in timeline:
        source = (event.get("source") or {}).get("issue") or {}
        pull = source.get("pull_request") or {}
        if event.get("event") == "cross-referenced" and pull.get("merged_at"):
            merge_sha = str(pull.get("merge_commit_sha") or "").lower()
            if FULL_SHA.fullmatch(merge_sha):
                merged.append(merge_sha)
    return Observation(
        number=number,
        state=str(issue.get("state") or "").lower(),
        labels=tuple(label["name"] for label in issue.get("labels", [])),
        receipts=receipts,
        merged_pull_request_shas=tuple(merged),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--target-branch", default="main")
    parser.add_argument(
        "--limit", type=int, default=25, help="max transitions applied per run"
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--summary", default=os.environ.get("GITHUB_STEP_SUMMARY"))
    args = parser.parse_args(argv)

    issues = (
        gh_api(
            f"repos/{args.repo}/issues",
            "--paginate",
            "-f",
            "state=all",
            "-f",
            f"labels={DONE_LABEL}",
            "-f",
            "per_page=100",
        )
        or []
    )
    issues = [i for i in issues if "pull_request" not in i]
    on_target = sha_on_target(args.repo, args.target_branch)
    decisions = [decide(observe(args.repo, issue), on_target) for issue in issues]
    refused = transitions(decisions)

    lines = [
        f"### oc-done guard — {args.repo}",
        "",
        f"claims audited: {len(decisions)}; refused: {len(refused)}",
        "",
    ]
    for t in refused:
        lines.append(
            f"- #{t['number']}: {t['reason']} {json.dumps(t['evidence'], sort_keys=True)}"
        )
    print("\n".join(lines))

    applied = 0
    if args.apply:
        for t in refused[: args.limit]:
            number = t["number"]
            subprocess.run(
                [
                    "gh",
                    "issue",
                    "edit",
                    str(number),
                    "--repo",
                    args.repo,
                    "--remove-label",
                    DONE_LABEL,
                    "--add-label",
                    "oc-validating",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "gh",
                    "issue",
                    "comment",
                    str(number),
                    "--repo",
                    args.repo,
                    "--body",
                    (
                        f"[OC-DONE-GUARD] `oc-done` withdrawn: {t['reason']} {json.dumps(t['evidence'], sort_keys=True)}. "
                        "Completion requires a closed issue, a receipt whose full implementation SHA is on "
                        f"`{args.target_branch}`, and changed files or a merged PR. Returned to `oc-validating`."
                    ),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            applied += 1
        lines.append(f"\ntransitions applied: {applied} (limit {args.limit})")

    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
