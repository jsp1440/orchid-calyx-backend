#!/usr/bin/env python3
"""Engine efficiency from durable GitHub evidence only (read-only).

Reports, for a time window: verified completed tasks (hosted settlement with a
verified merge), provider spend from the governor ledger (#1330), verified
tasks per dollar, cycle time, lease recoveries, first-attempt success, and how
many controller runs launched work. Every number is derived from a receipt and
lists the receipt ids it came from; anything not durably recorded (for example
prompt-cache token counts, which live only in worker artifacts) is reported as
``unavailable`` with the reason, never estimated.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

BOT = "github-actions[bot]"
LEDGER_ISSUE = 1330
CONTROLLER = "orchid-swarm-controller.yml"
RECEIPT = re.compile(
    r"^\[OC-GOVERNOR-COST\] run_id=(?P<run>\d+) issue=(?P<issue>\d+) "
    r"provider=(?P<provider>[\w-]+) reserved_usd=(?P<reserved>\d+(?:\.\d+)?)"
    r"(?: actual_usd=(?P<actual>\S+))?"
)
SETTLE = re.compile(
    r"^\[OC-GOVERNOR-COST-SETTLE\] run_id=(?P<run>\d+) "
    r"provider=(?P<provider>[\w-]+) actual_usd=(?P<actual>\d+(?:\.\d+)?)$"
)
CLAIM = re.compile(
    r"^\[OC-SWARM-V\d+\] Dependency/resource lease claimed: `(\{[^\n]+\})`"
)
TAGGED = re.compile(
    r"<!-- (?P<tag>OC-HOSTED-[A-Z-]+-V1)\s+(?P<json>\{.*?\})\s*-->", re.DOTALL
)
RECOVERY_PREFIX = "[OC-SWARM-V4] Stale lease recovered: `"


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _usd(value: str | None) -> Decimal | None:
    if not value or not re.fullmatch(r"\d+(?:\.\d+)?", value):
        return None
    return Decimal(value)


def gh(path: str) -> Any:
    out = subprocess.run(
        ["gh", "api", path], capture_output=True, text=True, timeout=60, check=True
    ).stdout
    return json.loads(out) if out.strip() else None


def paged(path: str, budget: int = 30) -> list[dict]:
    rows: list[dict] = []
    sep = "&" if "?" in path else "?"
    for page in range(1, budget + 1):
        batch = gh(f"{path}{sep}per_page=100&page={page}")
        batch = batch.get("workflow_runs") if isinstance(batch, dict) else batch
        if not isinstance(batch, list):
            break
        rows.extend(batch)
        if len(batch) < 100:
            break
    return rows


def ledger_spend(comments: list[dict], start: datetime, end: datetime) -> dict:
    """Per-provider spend in the window: actual where recorded, else reserved."""
    settled: dict[tuple[str, str], Decimal] = {}
    for c in comments:
        if (c.get("user") or {}).get("login") != BOT:
            continue
        for line in (c.get("body") or "").splitlines():
            m = SETTLE.match(line.strip())
            if m and m.group("provider") == "anthropic-checker":
                settled.setdefault(
                    (m.group("run"), m.group("provider")), Decimal(m.group("actual"))
                )
    rows = []
    for c in comments:
        if (c.get("user") or {}).get("login") != BOT:
            continue
        at = _time(c["created_at"])
        if not start <= at <= end:
            continue
        m = RECEIPT.match((c.get("body") or "").strip())
        if not m:
            continue
        actual = _usd(m.group("actual")) or settled.get(
            (m.group("run"), m.group("provider"))
        )
        rows.append(
            {
                "comment_id": c["id"],
                "run_id": m.group("run"),
                "issue": int(m.group("issue")),
                "provider": m.group("provider"),
                "reserved_usd": str(Decimal(m.group("reserved"))),
                "actual_usd": None if actual is None else str(actual),
                "counted_usd": str(
                    actual if actual is not None else Decimal(m.group("reserved"))
                ),
            }
        )
    by_provider: dict[str, dict[str, Any]] = {}
    for row in rows:
        entry = by_provider.setdefault(
            row["provider"], {"runs": 0, "actual_known": 0, "counted_usd": Decimal(0)}
        )
        entry["runs"] += 1
        entry["actual_known"] += row["actual_usd"] is not None
        entry["counted_usd"] += Decimal(row["counted_usd"])
    total = sum((e["counted_usd"] for e in by_provider.values()), Decimal(0))
    return {
        "receipts": rows,
        "by_provider": {
            k: {**v, "counted_usd": str(v["counted_usd"])}
            for k, v in sorted(by_provider.items())
        },
        "total_counted_usd": str(total),
    }


def issue_cycle(
    number: int, comments: list[dict], start: datetime, end: datetime
) -> dict | None:
    bot = [c for c in comments if (c.get("user") or {}).get("login") == BOT]
    claims = [c for c in bot if CLAIM.match(c.get("body") or "")]
    settlement = None
    for c in bot:
        for m in TAGGED.finditer(c.get("body") or ""):
            if m.group("tag") == "OC-HOSTED-SETTLEMENT-V1":
                try:
                    data = json.loads(m.group("json"))
                except ValueError:
                    continue
                if data.get("merge_sha"):
                    settlement = (c, data)
    if settlement is None:
        return None
    settled_at = _time(settlement[0]["created_at"])
    if not start <= settled_at <= end:
        return None
    first_claim = min((_time(c["created_at"]) for c in claims), default=None)
    recoveries = [c for c in bot if (c.get("body") or "").startswith(RECOVERY_PREFIX)]
    return {
        "issue": number,
        "settlement_comment": settlement[0]["id"],
        "merge_sha": settlement[1]["merge_sha"],
        "pr": (settlement[1].get("context") or {}).get("pr"),
        "claims": len(claims),
        "recoveries": len(recoveries),
        "first_attempt": len(claims) == 1,
        "cycle_minutes": None
        if first_claim is None
        else round((settled_at - first_claim).total_seconds() / 60, 1),
    }


def report(repo: str, start: datetime, end: datetime) -> dict:
    ledger = ledger_spend(
        paged(
            f"repos/{repo}/issues/{LEDGER_ISSUE}/comments?since={start:%Y-%m-%dT%H:%M:%SZ}"
        ),
        start,
        end,
    )
    issues = sorted({r["issue"] for r in ledger["receipts"]})
    cycles = []
    for number in issues:
        cycle = issue_cycle(
            number, paged(f"repos/{repo}/issues/{number}/comments"), start, end
        )
        if cycle:
            cycles.append(cycle)
    runs = [
        r
        for r in paged(
            f"repos/{repo}/actions/workflows/{CONTROLLER}/runs?created="
            f"{start:%Y-%m-%dT%H:%M:%SZ}..{end:%Y-%m-%dT%H:%M:%SZ}",
            budget=10,
        )
        if start <= _time(r["created_at"]) <= end
    ]
    worker_runs = {
        r["run_id"] for r in ledger["receipts"] if r["provider"] == "anthropic"
    }
    total = Decimal(ledger["total_counted_usd"])
    verified = len(cycles)
    minutes = [c["cycle_minutes"] for c in cycles if c["cycle_minutes"] is not None]
    return {
        "schema": "oc.engine-efficiency.v1",
        "repository": repo,
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "verified_completed_tasks": verified,
        "spend": ledger["by_provider"],
        "total_spend_usd": str(total),
        "verified_tasks_per_dollar": None
        if total == 0
        else round(float(verified / total), 2),
        "cost_per_verified_task_usd": None
        if verified == 0
        else str((total / verified).quantize(Decimal("0.0001"))),
        "checker_cost_basis": "actual"
        if all(
            r["actual_usd"] is not None
            for r in ledger["receipts"]
            if r["provider"] == "anthropic-checker"
        )
        else "reservation where no actual was recorded (see PR #1942)",
        "cycle_minutes": {
            "median": statistics.median(minutes) if minutes else None,
            "max": max(minutes) if minutes else None,
        },
        "lease_recoveries": sum(c["recoveries"] for c in cycles),
        "first_attempt_success": sum(c["first_attempt"] for c in cycles),
        "controller_runs": len(runs),
        "controller_runs_launching_paid_work": len(
            worker_runs & {str(r["id"]) for r in runs}
        ),
        "idle_controller_runs_fraction": None
        if not runs
        else round(1 - len(worker_runs & {str(r["id"]) for r in runs}) / len(runs), 3),
        "prompt_cache_effectiveness": "unavailable: cache token counts are recorded only in "
        "worker run artifacts, not in a durable receipt",
        "scientific_evidence_throughput": "not yet measured: no receipt distinguishes "
        "scientific deliverables from engineering fixes",
        "cycles": cycles,
        "ledger_receipts": ledger["receipts"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="jsp1440/orchid-calyx-backend")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", default=None)
    args = parser.parse_args(argv)
    start = _time(args.start)
    end = _time(args.end) if args.end else datetime.now(timezone.utc)
    json.dump(
        report(args.repository, start, end),
        sys.stdout,
        indent=1,
        sort_keys=True,
        default=str,
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
