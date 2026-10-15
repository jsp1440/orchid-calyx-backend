#!/usr/bin/env python3
"""Bind paid provider admission to an owner authorization on the issue itself.

Budget, kill switch and NO-API gates say *whether* paid execution may run. They
do not say *which* work it may run on: the first governed window (#1823) spent
on ten issues nobody authorized, after blocked reconciliation re-queued them
when a budget variable changed. This gate closes that gap at the last point
before a provider call. A worker may call a paid provider only for an issue
that carries exactly one valid owner ``OC-HOSTED-FACTORY-AUTHORIZATION-V1``
record bound to the issue's current material, unexpired, low/moderate risk.

The check is the same ``authorization()`` the hosted checker already enforces,
so a task that could never be integrated also cannot be paid for. It makes no
provider call, fails closed on any read error, and never mutates state; the
caller parks a denial through the existing governor denial path, where
blocked reconciliation holds ``governor:`` blockers as owner-gated.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import oc_hosted_completion as hosted

DENIAL = "OWNER_ISSUE_AUTHORIZATION_REQUIRED"


def admit(repository: str, issue_number: int, *, fetch=None, now=None) -> dict:
    """Return the admission decision; never raises for an ordinary refusal."""
    fetch = fetch or _fetch
    try:
        issue, comments = fetch(repository, issue_number)
        if issue.get("pull_request") or issue.get("state") != "open":
            raise ValueError("issue_not_open")
        grant = hosted.authorization(issue, comments, repository, now)
    except Exception as exc:  # noqa: BLE001 - every failure is a refusal
        return {
            "authorized": False,
            "reason": DENIAL,
            "detail": str(exc) or type(exc).__name__,
            "issue": issue_number,
        }
    return {
        "authorized": True,
        "reason": "",
        "detail": "owner_authorization_valid",
        "issue": issue_number,
        "authorization_comment": grant["comment_id"],
        "expires_at": grant["expires_at"],
    }


def _fetch(repository: str, issue_number: int):
    issue = hosted.api(repository, f"issues/{issue_number}")
    comments = hosted.pages(repository, f"issues/{issue_number}/comments")
    return issue, comments


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", type=int, required=True)
    args = parser.parse_args()
    decision = admit(args.repository, args.issue_number)
    print(
        "[OC-PAID-ISSUE-ADMISSION] "
        + ("authorized" if decision["authorized"] else "denied")
        + f" issue=#{decision['issue']} detail={decision['detail']}"
    )
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(
                f"authorized={'true' if decision['authorized'] else 'false'}\n"
            )
            handle.write(f"reason={decision['reason']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
