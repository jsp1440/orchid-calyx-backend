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
RUN_PROVIDER_RE = re.compile(
    r"\brun_id=(?P<run>\d+)\b.*?\bprovider=(?P<provider>[\w-]+)"
)
# A receipt written before a provider call can only hold the reservation (the
# hosted checker reserves before credentials initialize). Once the call has
# returned, one settle line per (run, provider) records the real cost; it
# replaces that run's reservation in the totals and is never counted alone.
SETTLE_TAG = "[OC-GOVERNOR-COST-SETTLE]"
SETTLE_RE = re.compile(
    r"^\[OC-GOVERNOR-COST-SETTLE\] run_id=(?P<run>\d+) provider=(?P<provider>[\w-]+) "
    r"actual_usd=(?P<actual>\S+)$"
)


def _usd(value: str | None) -> Decimal | None:
    """A plain non-negative decimal amount, or None for anything else."""
    if not value or not USD_RE.fullmatch(value):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def receipt_spend(
    line: str, settled: dict[tuple[str, str], Decimal] | None = None
) -> tuple[Decimal, str, str] | None:
    """Spend counted for one receipt: the recorded actual cost when known.

    The reservation is the pre-run estimate. When the run recorded its real
    provider cost, on the receipt itself or in a later settle line for the
    same run and provider, that is what the budget counts; otherwise (provider
    failure, unpriced model, older receipts) the reservation stands.
    """
    match = RECEIPT_RE.search(line)
    if not match:
        return None
    value = _usd(match.group("actual"))
    if value is None and settled:
        key = RUN_PROVIDER_RE.search(line)
        if key:
            value = settled.get((key.group("run"), key.group("provider")))
    if value is None:
        value = _usd(match.group("reserved"))
    if value is None:
        return None
    return value, match.group("date"), match.group("month")


def settlements(lines: list[str]) -> dict[tuple[str, str], Decimal]:
    """Settled actual cost per (run_id, provider); the first valid line wins.

    Callers must pass only lines written by the workflow bot (``snapshot``
    filters by author): a settle line replaces a reservation, so an untrusted
    one could lower counted spend.
    """
    found: dict[tuple[str, str], Decimal] = {}
    for line in lines:
        match = SETTLE_RE.match(line.strip())
        if not match:
            continue
        value = _usd(match.group("actual"))
        key = (match.group("run"), match.group("provider"))
        if value is not None and key not in found:
            found[key] = value
    return found


def _gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh command failed")
    return result.stdout


#: Settle lines lower counted spend, so only the workflow bot may write them.
#: #1330 is a public, unlocked issue: anyone could otherwise post one (review of
#: #1942). gh's GraphQL author login for the Actions bot is "github-actions".
SETTLE_AUTHORS = frozenset({"github-actions", "github-actions[bot]"})
SETTLE_PROVIDERS = frozenset({"anthropic-checker"})


def _ledger_rows(raw: str) -> list[tuple[str | None, str]]:
    """(author, body line) pairs; a line without author info has author None.

    Receipts from any author still count (they can only raise spend, which
    fails closed); settle lines are trusted only from ``SETTLE_AUTHORS``.
    """
    rows: list[tuple[str | None, str]] = []
    for record in raw.splitlines():
        author, body = None, record
        try:
            decoded = json.loads(record)
        except ValueError:
            decoded = None
        if isinstance(decoded, dict) and isinstance(decoded.get("b"), str):
            author = decoded.get("a") if isinstance(decoded.get("a"), str) else None
            body = decoded["b"]
        rows.extend((author, line) for line in body.splitlines())
    return rows


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
        ".comments[] | {a: .author.login, b: .body} | @json",
    )
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    month = now.strftime("%Y-%m")
    daily = Decimal(0)
    monthly = Decimal(0)
    rows = _ledger_rows(raw)
    lines = [line for _, line in rows]
    settled = {
        key: value
        for key, value in settlements(
            [line for author, line in rows if author in SETTLE_AUTHORS]
        ).items()
        if key[1] in SETTLE_PROVIDERS
    }
    for line in lines:
        spend = receipt_spend(line, settled)
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


def append_settlement(
    repo: str, ledger_issue: int, *, run_id: str, provider: str, actual_usd: str
) -> bool:
    """Record a run's real provider cost; False (and no write) if not a decimal."""
    value = _usd(actual_usd)
    if value is None or not str(run_id).isdigit() or provider not in SETTLE_PROVIDERS:
        return False
    body = f"{SETTLE_TAG} run_id={run_id} provider={provider} actual_usd={value}"
    _gh("issue", "comment", str(ledger_issue), "--repo", repo, "--body", body)
    return True


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
