"""GitHub-native durable spend ledger helpers for governed provider runs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

RECEIPT_RE = re.compile(
    r"\[OC-GOVERNOR-COST\].*?reserved_usd=(?P<reserved>\d+(?:\.\d+)?)"
    r"(?: actual_usd=(?P<actual>\S+))?"
    r".*?date=(?P<date>\d{4}-\d{2}-\d{2}).*?month=(?P<month>\d{4}-\d{2})"
)
USD_RE = re.compile(r"\d+(?:\.\d+)?")


def _usd(value: str | None) -> Decimal | None:
    """A plain non-negative decimal amount, or None for anything else."""
    if not value or not USD_RE.fullmatch(value):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def receipt_spend(line: str) -> tuple[Decimal, str, str] | None:
    """Spend counted for one receipt: the recorded actual cost when known.

    The reservation is the pre-run estimate. When the run recorded its real
    provider cost, that is what the budget counts; otherwise (provider failure,
    unpriced model, older receipts) the reservation stands.
    """
    match = RECEIPT_RE.search(line)
    if not match:
        return None
    value = _usd(match.group("actual"))
    if value is None:
        value = _usd(match.group("reserved"))
    if value is None:
        return None
    return value, match.group("date"), match.group("month")


def _gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh command failed")
    return result.stdout


def snapshot(repo: str, ledger_issue: int) -> tuple[Decimal, Decimal]:
    raw = _gh(
        "issue",
        "view",
        str(ledger_issue),
        "--repo",
        repo,
        "--json",
        "comments",
        "--jq",
        ".comments[].body",
    )
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    daily = Decimal(0)
    monthly = Decimal(0)
    for line in raw.splitlines():
        spend = receipt_spend(line)
        if spend is None:
            continue
        value, date, receipt_month = spend
        if receipt_month == month:
            monthly += value
        if date == today:
            daily += value
    return daily, monthly


def append_receipt(
    repo: str,
    ledger_issue: int,
    *,
    run_id: str,
    issue_number: str,
    provider: str,
    reserved_usd: Decimal,
    actual_usd: str,
) -> None:
    now = datetime.now(timezone.utc)
    body = (
        "[OC-GOVERNOR-COST] "
        f"run_id={run_id} issue={issue_number} provider={provider} "
        f"reserved_usd={reserved_usd} actual_usd={_usd(actual_usd) or 'unknown'} "
        f"date={now:%Y-%m-%d} month={now:%Y-%m}"
    )
    _gh(
        "issue",
        "comment",
        str(ledger_issue),
        "--repo",
        repo,
        "--body",
        body,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", ""))
    parser.add_argument("--ledger-issue", type=int, default=1330)
    parser.add_argument("--github-output", default=os.getenv("GITHUB_OUTPUT", ""))
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--run-id", default=os.getenv("GITHUB_RUN_ID", ""))
    parser.add_argument("--issue-number", default="")
    parser.add_argument("--provider", default="")
    parser.add_argument("--reserved-usd", default="")
    parser.add_argument("--actual-usd", default="")
    args = parser.parse_args()

    if not args.repo:
        raise SystemExit("GITHUB_REPOSITORY_REQUIRED")

    if args.append:
        try:
            reserved = Decimal(args.reserved_usd)
        except InvalidOperation as exc:
            raise SystemExit("INVALID_RESERVED_USD") from exc
        append_receipt(
            args.repo,
            args.ledger_issue,
            run_id=args.run_id,
            issue_number=args.issue_number,
            provider=args.provider,
            reserved_usd=reserved,
            actual_usd=args.actual_usd,
        )
        return 0

    daily, monthly = snapshot(args.repo, args.ledger_issue)
    payload = {"daily_spend_usd": str(daily), "monthly_spend_usd": str(monthly)}
    print(json.dumps(payload, sort_keys=True))
    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as handle:
            handle.write(f"daily_spend_usd={daily}\n")
            handle.write(f"monthly_spend_usd={monthly}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
