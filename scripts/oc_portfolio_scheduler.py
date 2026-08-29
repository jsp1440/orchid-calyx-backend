#!/usr/bin/env python3
"""Deterministic priority-aware portfolio selection for the continuous-completion control plane.

The GitHub Actions scheduler (`.github/workflows/orchid-continuous-completion.yml`)
used to keep a hard-coded legacy backlog array and fill most of its dispatch
capacity from that array before it ever looked at the general `oc-queued`
portfolio. That permanently outranked newly created P0/P1 completion work.

This module replaces that mechanism with a pure, deterministic, stdlib-only
planner. The workflow collects a snapshot of open issues and open integration
PRs with `gh`, pipes it here, and dispatches exactly what the plan says. Keeping
the policy in an importable module (instead of inline bash) is what makes the
behaviour testable in `tests/test_oc_portfolio_scheduler.py`.

Policy summary
--------------
* The canonical execution portfolio is every open issue labelled ``oc-queued``.
* Priority comes from an explicit ``oc-p0``..``oc-p5`` label. Only when no
  explicit priority exists is it derived from a leading ``P<n>`` title token.
  Issue text is never mined for priority beyond that single stable token.
* Unclassified queued work ranks immediately below every explicit priority band
  except P5: it sorts after an explicit P4 but ahead of P5 idle capacity, so
  idle-capacity work can never take a lane while real unclassified work waits.
* Ordering is priority first, then oldest eligible issue first, then issue
  number. P5 is an idle-capacity band and is admitted only when no higher
  priority eligible work is waiting.
* Capacity is ``MAX_ACTIVE_LANES`` minus the *active execution leases*
  (``oc-running``). ``oc-validating``/``oc-blocked``/``oc-owner-gate``/``oc-done``
  never consume an execution lane.
* An issue with a durable integration PR is not redispatched unless ``oc-repair``
  explicitly authorises one more bounded worker pass; repair keeps a reserved
  lane so failed exact-head work cannot be starved by new work.
* Bounded fairness: at most one lane per cycle is reserved for the oldest
  eligible issue that strict priority order would otherwise leave behind.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from typing import Any

MAX_ACTIVE_LANES = 5
REPAIR_RESERVED_LANES = 1
FAIRNESS_WAIT_HOURS = 24
FAIRNESS_RESERVED_LANES = 1
DEFAULT_PRIORITY = 4
IDLE_PRIORITY = 5
LOWEST_PRIORITY = 5

QUEUED = "oc-queued"
RUNNING = "oc-running"
VALIDATING = "oc-validating"
REPAIR = "oc-repair"
BLOCKED = "oc-blocked"
#: Parked by the repository-wide Claude runtime circuit; not an execution candidate.
RUNTIME_BACKOFF = "oc-runtime-backoff"
REPAIR_BACKOFF = "oc-repair-backoff"
OWNER_GATE = "oc-owner-gate"
DONE = "oc-done"

#: Labels that hold an issue outside the execution portfolio entirely.
NON_EXECUTABLE_LABELS = (BLOCKED, OWNER_GATE, DONE, RUNTIME_BACKOFF, REPAIR_BACKOFF)

PRIORITY_LABELS = tuple(f"oc-p{level}" for level in range(LOWEST_PRIORITY + 1))

#: A single stable leading token such as ``P0 OC-COMPLETE-001 — ...`` or ``[P1] ...``.
TITLE_PRIORITY_RE = re.compile(r"^\s*[\[(]?\s*P([0-5])\s*[\])]?(?=\b|_)")
AUTO_ISSUE_MARKER_RE = re.compile(r"OC-AUTO-ISSUE:\s*#(\d+)")

_FAR_FUTURE = datetime(9999, 1, 1, tzinfo=timezone.utc)


def priority_label(level: int) -> str:
    """Return the canonical durable label for a priority level."""
    return f"oc-p{level}"


def label_names(issue: dict) -> list[str]:
    """Normalise ``labels`` from either the gh CLI shape or a plain string list."""
    names: list[str] = []
    for label in issue.get("labels") or []:
        if isinstance(label, str):
            names.append(label)
        elif isinstance(label, dict) and label.get("name"):
            names.append(str(label["name"]))
    return names


def resolve_priority(issue: dict) -> tuple[int, str]:
    """Resolve (priority, source) for an issue.

    An explicit ``oc-p<n>`` label always wins over the title token so that a
    deliberate owner/governance decision is never overridden by wording.
    """
    explicit = sorted(
        level
        for level in range(LOWEST_PRIORITY + 1)
        if priority_label(level) in label_names(issue)
    )
    if explicit:
        return explicit[0], "label"
    match = TITLE_PRIORITY_RE.match(str(issue.get("title") or ""))
    if match:
        return int(match.group(1)), "title"
    return DEFAULT_PRIORITY, "default"


def durable_pr_index(pull_requests: Iterable[dict]) -> dict[int, int]:
    """Map issue number -> lowest open durable integration PR number."""
    index: dict[int, int] = {}
    for pr in pull_requests or []:
        number = pr.get("number")
        if number is None:
            continue
        for raw_issue in AUTO_ISSUE_MARKER_RE.findall(str(pr.get("body") or "")):
            issue = int(raw_issue)
            current = index.get(issue)
            if current is None or int(number) < current:
                index[issue] = int(number)
    return index


def parse_timestamp(value: Any) -> datetime:
    """Parse an ISO-8601/GitHub timestamp, sorting unparseable values last."""
    if not value:
        return _FAR_FUTURE
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return _FAR_FUTURE
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _now(snapshot: dict) -> datetime:
    supplied = snapshot.get("now")
    if supplied:
        return parse_timestamp(supplied)
    return datetime.now(timezone.utc)


def _candidate(
    issue: dict,
    durable: dict[int, int],
    now: datetime,
    stabilization_issue: int | None = None,
) -> dict:
    labels = label_names(issue)
    number = int(issue["number"])
    priority, source = resolve_priority(issue)
    created = parse_timestamp(issue.get("createdAt") or issue.get("created_at"))
    waited = 0.0 if created is _FAR_FUTURE else max(
        0.0, (now - created).total_seconds() / 3600.0
    )
    return {
        "number": number,
        "title": issue.get("title") or "",
        "labels": labels,
        "priority": priority,
        "priority_source": source,
        "priority_label": priority_label(priority),
        "created_at": created,
        "waited_hours": round(waited, 3),
        "repair": REPAIR in labels,
        "durable_pr": durable.get(number),
        "canonical_stabilization": number == stabilization_issue,
        "band": 1 if priority >= IDLE_PRIORITY else 0,
    }


def _order_key(candidate: dict) -> tuple:
    return (
        0 if candidate["canonical_stabilization"] else 1,
        candidate["band"],
        candidate["priority"],
        # An explicit priority always outranks the same level reached by default.
        1 if candidate["priority_source"] == "default" else 0,
        candidate["created_at"],
        candidate["number"],
    )


def _public(candidate: dict, **extra: Any) -> dict:
    payload = {
        key: value
        for key, value in candidate.items()
        if key not in {"created_at", "labels"}
    }
    payload["created_at"] = (
        None if candidate["created_at"] is _FAR_FUTURE
        else candidate["created_at"].isoformat().replace("+00:00", "Z")
    )
    payload.update(extra)
    return payload


def build_plan(snapshot: dict) -> dict:
    """Build a deterministic dispatch plan from a repository snapshot.

    ``snapshot`` accepts ``issues`` (open issues with number/title/labels/createdAt),
    ``pull_requests`` (open PRs against the integration branch with number/body),
    and optional ``max_active_lanes``/``now`` overrides.
    """
    issues = list(snapshot.get("issues") or [])
    durable = durable_pr_index(snapshot.get("pull_requests") or [])
    now = _now(snapshot)
    max_lanes = int(snapshot.get("max_active_lanes") or MAX_ACTIVE_LANES)
    stabilization_issue = snapshot.get("stabilization_issue")
    if stabilization_issue is not None:
        stabilization_issue = int(stabilization_issue)

    active: list[dict] = []
    eligible: list[dict] = []
    suppressed: list[dict] = []

    for issue in issues:
        if issue.get("number") is None:
            continue
        if str(issue.get("state") or "OPEN").upper() not in {"OPEN", ""}:
            continue
        candidate = _candidate(issue, durable, now, stabilization_issue)
        labels = candidate["labels"]

        if RUNNING in labels:
            active.append(candidate)
            continue
        if QUEUED not in labels:
            continue
        blocking = [label for label in NON_EXECUTABLE_LABELS if label in labels]
        if blocking:
            suppressed.append(_public(candidate, reason=blocking[0]))
            continue
        if candidate["durable_pr"] is not None and not candidate["repair"]:
            # Durable PR lineage owns the next transition; redispatching Claude
            # here is duplicate spend on work that is already delivered.
            suppressed.append(_public(candidate, reason="durable-pr"))
            continue
        eligible.append(candidate)

    active.sort(key=_order_key)
    eligible.sort(key=_order_key)

    # A declared canonical stabilization mission freezes ordinary portfolio
    # expansion. It is the only selectable issue while eligible; other work is
    # preserved in the queue and reported as suppressed rather than relabelled.
    canonical = [c for c in eligible if c["canonical_stabilization"]]
    if canonical:
        for candidate in eligible:
            if not candidate["canonical_stabilization"]:
                suppressed.append(_public(candidate, reason="stabilization-freeze"))
        eligible = canonical
    capacity = max(0, max_lanes - len(active))

    selected: list[dict] = []
    taken: set[int] = set()

    def take(candidate: dict, reason: str) -> None:
        if candidate["number"] in taken:
            return
        taken.add(candidate["number"])
        selected.append(_public(candidate, selection_reason=reason))

    band0 = [c for c in eligible if c["band"] == 0]
    idle = [c for c in eligible if c["band"] == 1]

    # 1. Reserved repair capacity: a failed exact-head slice must not be starved
    #    by a continuously refilling stream of new higher-priority work.
    for candidate in [c for c in band0 if c["repair"]][:REPAIR_RESERVED_LANES]:
        if len(selected) >= capacity:
            break
        take(candidate, "repair-reserved")

    remaining = max(0, capacity - len(selected))
    pool = [c for c in band0 if c["number"] not in taken]

    # 2. Bounded fairness: reserve at most one lane for the oldest eligible issue
    #    that strict priority order would otherwise leave behind this cycle.
    fairness: dict | None = None
    if remaining >= 2:
        starved = [
            c
            for c in pool[remaining - FAIRNESS_RESERVED_LANES :]
            if c["waited_hours"] >= FAIRNESS_WAIT_HOURS
        ]
        if starved:
            fairness = min(
                starved, key=lambda c: (c["created_at"], c["number"])
            )
            remaining -= FAIRNESS_RESERVED_LANES

    # 3. Strict priority fill.
    for candidate in pool:
        if len(selected) >= capacity or remaining <= 0:
            break
        if fairness is not None and candidate["number"] == fairness["number"]:
            continue
        take(candidate, "priority")
        remaining -= 1

    if fairness is not None and len(selected) < capacity:
        take(fairness, "fairness")

    # 4. P5 idle-capacity work is admitted only when no higher-priority eligible
    #    work is still waiting for a lane.
    waiting_band0 = [c for c in band0 if c["number"] not in taken]
    if not waiting_band0:
        for candidate in idle:
            if len(selected) >= capacity:
                break
            take(candidate, "idle-capacity")

    return {
        "max_active_lanes": max_lanes,
        "active_lanes": [_public(c) for c in active],
        "active_lane_count": len(active),
        "available_capacity": capacity,
        "ranking": [_public(c) for c in eligible],
        "eligible_count": len(eligible),
        "selected": selected,
        "selected_numbers": [c["number"] for c in selected],
        "suppressed": suppressed,
        "fairness_reservation": None if fairness is None else fairness["number"],
        "generated_at": now.isoformat().replace("+00:00", "Z"),
    }


def priority_label_fixes(issues: Iterable[dict]) -> list[dict]:
    """Durable priority representation: labels that should be added/removed.

    Only issues that already carry an orchestration label are normalised, so the
    scheduler never labels unrelated repository issues.
    """
    fixes: list[dict] = []
    orchestration = {QUEUED, RUNNING, VALIDATING, REPAIR, BLOCKED, OWNER_GATE, DONE}
    for issue in issues or []:
        labels = label_names(issue)
        if not orchestration.intersection(labels):
            continue
        priority, source = resolve_priority(issue)
        if source == "label":
            continue
        desired = priority_label(priority)
        stale = [l for l in labels if l in PRIORITY_LABELS and l != desired]
        fixes.append(
            {
                "number": int(issue["number"]),
                "add": desired,
                "remove": stale,
                "source": source,
            }
        )
    return fixes


def _load(path: str | None) -> dict:
    if path in (None, "-"):
        raw = sys.stdin.read()
    else:
        with open(path, encoding="utf-8") as handle:
            raw = handle.read()
    return json.loads(raw or "{}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="-", help="snapshot JSON path ('-' for stdin)")
    parser.add_argument(
        "--mode",
        choices=("plan", "priority-labels", "selected"),
        default="plan",
    )
    parser.add_argument("--max-active-lanes", type=int, default=None)
    args = parser.parse_args(argv)

    snapshot = _load(args.input)
    if args.max_active_lanes is not None:
        snapshot["max_active_lanes"] = args.max_active_lanes

    if args.mode == "priority-labels":
        json.dump(priority_label_fixes(snapshot.get("issues") or []), sys.stdout)
        sys.stdout.write("\n")
        return 0

    plan = build_plan(snapshot)
    if args.mode == "selected":
        for number in plan["selected_numbers"]:
            print(number)
        return 0
    json.dump(plan, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
