#!/usr/bin/env python3
"""Bind paid provider admission to an owner authorization on the issue itself.

Budget, kill switch and NO-API gates say *whether* paid execution may run. They
do not say *which* work it may run on: the first governed window (#1823) spent
on ten issues nobody authorized, after blocked reconciliation re-queued them
when a budget variable changed. This gate closes that gap at the last point
before a provider call. A worker may call a paid provider only for an issue
that carries exactly one valid owner ``OC-HOSTED-FACTORY-AUTHORIZATION-V1``
record bound to the issue's current material, unexpired, low/moderate risk,
or, without one, falls inside the owner's standing grant on issue #1924 --
either the per-issue standing grant (owner-opened issues listed by digest) or
the policy-scoped discovery grant for issues the engine filed itself.

A discovery admission is additionally bounded here, where it is about to cost
money: the route's reservation must not exceed the grant's per-issue ceiling,
and at most ``max_issues_per_day`` discovery admissions are made per UTC day,
counted from durable ``[OC-DISCOVERY-ADMISSION]`` receipts the workflow bot
wrote on the governor ledger issue. The receipt is written and read back before
admission is reported, so the count survives the run; a run the governor then
refuses still consumes its slot, which errs towards fewer paid runs. Deleting a
receipt needs a token, and the paid worker runs every model-driven subprocess
without one (``swarm_anthropic_direct.tool_environment``). The grant's exact
paths are written into the worker's packet as its ``Allowed paths:``, so a
discovered issue never runs with an unbounded write scope.

A daily-cap, reservation-ceiling or unreadable-authority refusal is not an
owner decision: it is reported with its own reason and ``requeue=true``, and
the lane returns the issue to the queue instead of parking it as owner-gated.
All budget, kill-switch, NO-API and paid-concurrency gates still apply after
this. No grant admitted here authorizes merge to main, deployment or any
scientific activation.

The check is the same ``authorization()`` the hosted checker already enforces,
so a task that could never be integrated also cannot be paid for. It makes no
provider call, fails closed on any read or write error, and mutates nothing
except the one discovery receipt above; the caller parks a denial through the existing governor denial path, where
blocked reconciliation holds ``governor:`` blockers as owner-gated.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import oc_hosted_completion as hosted
from scripts.swarm_anthropic_direct import _parse_allowed_paths

DENIAL = "OWNER_ISSUE_AUTHORIZATION_REQUIRED"
LEDGER_ISSUE = 1330
RECEIPT_TAG = "[OC-DISCOVERY-ADMISSION]"
RECEIPT_AUTHOR = "github-actions[bot]"
DAILY_CAP = "DISCOVERY_DAILY_CAP_REACHED"
CEILING = "DISCOVERY_RESERVATION_ABOVE_GRANT"
UNAVAILABLE = "DISCOVERY_AUTHORITY_UNAVAILABLE"
RECEIPT = re.compile(
    r"^\[OC-DISCOVERY-ADMISSION\] grant=[0-9]+ issue=[0-9]+ run_id=\S+ "
    r"date=(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})$",
    re.MULTILINE,
)


class Deferred(ValueError):
    """A refusal that is not an owner decision: the issue goes back to queue."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason


class GitHubLedger:
    """Discovery admission receipts on the governor ledger issue."""

    def __init__(self, repository: str) -> None:
        self.repository = repository

    def since(self, moment: str) -> list[dict]:
        # ``since`` bounds the read to rows touched today, so the ledger's
        # length never truncates the count.
        return hosted.pages(
            self.repository, f"issues/{LEDGER_ISSUE}/comments?since={moment}"
        )

    def append(self, body: str) -> int:
        return hosted.comment(self.repository, LEDGER_ISSUE, body)


def admitted_today(rows: list[dict], day: str) -> int:
    """Discovery admission receipts the workflow bot wrote on ``day``.

    Only the bot's rows count, so nobody else can exhaust the cap by posting
    lookalikes. A bot row created that day that carries the tag but no
    well-formed receipt still counts once: unreadable is not absent.
    """
    total = 0
    for row in rows:
        body = row.get("body") or ""
        if (row.get("user") or {}).get("login") != RECEIPT_AUTHOR:
            continue
        if RECEIPT_TAG not in body:
            continue
        dated = sum(m["date"] == day for m in RECEIPT.finditer(body))
        created = str(row.get("created_at") or "").startswith(day)
        total += dated or int(created)
    return total


def bind_packet(packet_file, allowed) -> None:
    """Make the worker's packet declare exactly the admitted write scope.

    A discovered issue declares no ``Allowed paths:``, so the worker would run
    unbounded. The grant's paths are appended as the declaration; one the
    packet already carries must equal them. Read back through the worker's
    own parser, so what is checked is what the worker will enforce.
    """
    hosted.require(packet_file and allowed, "discovery_packet_unbound")
    path = Path(packet_file)
    text = path.read_text(encoding="utf-8")
    if _parse_allowed_paths(text) is None:
        listing = "".join(f"- `{item}`\n" for item in allowed)
        path.write_text(
            text.rstrip("\n") + "\n\nAllowed paths:\n" + listing, encoding="utf-8"
        )
    declared = _parse_allowed_paths(path.read_text(encoding="utf-8"))
    hosted.require(declared and declared == set(allowed), "discovery_packet_unbound")


def admit_discovery(
    grant, issue_number, *, reserved_usd, ledger, now, run_id, packet_file
):
    """Ceiling, daily cap and packet scope; then record the durable receipt."""
    try:
        reserved = Decimal(str(reserved_usd))
    except InvalidOperation:
        raise Deferred(CEILING, "discovery_reservation_unknown") from None
    if not (
        reserved.is_finite()
        and reserved > 0
        and reserved <= Decimal(grant["max_reserved_usd_per_issue"])
    ):
        raise Deferred(CEILING, "discovery_reservation_exceeds_grant")
    hosted.require(re.fullmatch(r"[0-9]+", run_id or ""), "discovery_run_unknown")
    moment = now or datetime.now(UTC)
    day = moment.date().isoformat()
    start = datetime.combine(moment.date(), time(), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows = ledger.since(start)
    except Exception as exc:
        raise Deferred(UNAVAILABLE, "discovery_ledger_unavailable") from exc
    count = admitted_today(rows, day)
    if count >= grant["max_issues_per_day"]:
        raise Deferred(DAILY_CAP, "discovery_daily_cap_reached")
    bind_packet(packet_file, grant["allowed_paths"])
    try:
        ledger.append(
            f"{RECEIPT_TAG} grant={grant['comment_id']} issue={issue_number} "
            f"run_id={run_id} date={day}"
        )
    except Exception as exc:
        raise Deferred(UNAVAILABLE, "discovery_receipt_unconfirmed") from exc
    return count + 1


def admit(
    repository: str,
    issue_number: int,
    *,
    fetch=None,
    now=None,
    reserved_usd=None,
    ledger=None,
    run_id=None,
    packet_file=None,
) -> dict:
    """Return the admission decision; never raises for an ordinary refusal."""
    fetch = fetch or _fetch
    try:
        issue, comments, *extra = fetch(repository, issue_number)
        if issue.get("pull_request") or issue.get("state") != "open":
            raise ValueError("issue_not_open")
        grant = hosted.authorization(
            issue,
            comments,
            repository,
            now,
            extra[0] if extra else None,
            extra[1] if len(extra) > 1 else None,
        )
        if grant.get("discovery"):
            admit_discovery(
                grant,
                issue_number,
                reserved_usd=reserved_usd,
                ledger=ledger or GitHubLedger(repository),
                now=now,
                run_id=run_id if run_id is not None else os.getenv("GITHUB_RUN_ID", ""),
                packet_file=packet_file,
            )
    except Deferred as exc:
        return _refusal(exc.reason, exc, issue_number, requeue=True)
    except hosted.AuthorizationUnavailable as exc:
        return _refusal(UNAVAILABLE, exc, issue_number, requeue=True)
    except Exception as exc:  # noqa: BLE001 - every failure is a refusal
        return _refusal(DENIAL, exc, issue_number)
    return {
        "authorized": True,
        "reason": "",
        "detail": "owner_authorization_valid",
        "issue": issue_number,
        "authorization_comment": grant["comment_id"],
        "standing": bool(grant.get("standing")),
        "discovery": bool(grant.get("discovery")),
        "expires_at": grant["expires_at"],
    }


def _refusal(reason, exc, issue_number, *, requeue=False) -> dict:
    refusal = {
        "authorized": False,
        "reason": reason,
        "detail": str(exc) or type(exc).__name__,
        "issue": issue_number,
    }
    if requeue:
        refusal["requeue"] = True
    return refusal


def _fetch(repository: str, issue_number: int):
    issue = hosted.api(repository, f"issues/{issue_number}")
    comments = hosted.pages(repository, f"issues/{issue_number}/comments")
    # Read only when the issue has no per-issue record of its own.
    return (
        issue,
        comments,
        lambda: hosted.standing_comments(repository),
        lambda: hosted.issue_edit_history(repository, issue_number),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--issue-number", type=int, required=True)
    # The route's per-run reservation; only a discovery admission reads it.
    parser.add_argument("--reserved-usd", default="")
    # The worker's packet; a discovery admission writes its scope into it.
    parser.add_argument("--packet-file", default="")
    args = parser.parse_args()
    decision = admit(
        args.repository,
        args.issue_number,
        reserved_usd=args.reserved_usd,
        packet_file=args.packet_file,
    )
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
            handle.write(f"requeue={'true' if decision.get('requeue') else 'false'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
