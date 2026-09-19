#!/usr/bin/env python3
"""Decide which blocked issues are still blocked, and say why for the rest.

``oc-blocked`` is a one-way door. ``oc_portfolio_scheduler`` lists it in
``NON_EXECUTABLE_LABELS``, which holds an issue outside the execution portfolio
entirely, and the only code that removes the label runs *after* a lane executes
the issue — which a blocked issue is never selected for. So nothing takes work
back out, whatever happens to the thing that stopped it.

That is how #1502 sat blocked on ``BLOCKED_MONTHLY_BUDGET_EXCEEDED`` for a day
after the routing defect behind that denial had been repaired and merged. The
blocker was gone; nothing was looking.

This module decides nothing on its own authority and mutates nothing. It reads
issues and the state of what they say blocks them, and returns a disposition per
issue. A caller applies them.

WHAT IT WILL NOT DO

* Release on age. "It has been a while" is not evidence that a blocker cleared,
  and a reconciler that believed it would re-admit genuinely blocked work on a
  timer.
* Release anything owner-gated — a credential, an authorization, a spending
  decision. Those are not this system's to clear, and a structured record saying
  so is honoured as a permanent hold rather than a checkable condition.
* Release work explicitly parked with ``OC-AUTO-REQUEUE: false``.
* Release an issue whose blocker it cannot check. An unverifiable blocker is
  *reported*, never released: guessing would re-admit work that is genuinely
  stopped, and the honest output is a list someone can act on.

That last case is the common one today, because the existing blocked issues
record their blockers in prose, as ``AGENTS.md`` asks. They are surfaced here
rather than released, which turns a silent one-way door into a visible queue.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

BLOCKED = "oc-blocked"
OWNER_GATE = "oc-owner-gate"

#: Machine-readable blocker record, in the ``BLOCKED`` comment ``AGENTS.md``
#: already requires. The prose stays; this makes one line of it checkable.
BLOCKED_ON = re.compile(r"^OC-BLOCKED-ON:\s*(?P<ref>\S+)\s*$", re.IGNORECASE | re.MULTILINE)

#: An explicit refusal to be re-queued automatically, used by the Stage C
#: canaries. It outranks every other signal here.
NO_REQUEUE = re.compile(r"^OC-AUTO-REQUEUE:\s*false\s*$", re.IGNORECASE | re.MULTILINE)

#: Blocker forms this module can check.
ISSUE_REF = re.compile(r"^(?:issue)?#(?P<number>\d+)$", re.IGNORECASE)
PR_REF = re.compile(r"^pr#(?P<number>\d+)$", re.IGNORECASE)

#: Blocker forms that are a person's decision. Recognised so they are held
#: deliberately and reported as owner-gated, rather than falling into the
#: unverifiable pile where they would read as an oversight.
OWNER_FORMS = frozenset(
    {
        "owner-decision",
        "owner-authorization",
        "credential",
        "credentials",
        "secret",
        "spend",
        "budget-increase",
        "deployment",
    }
)


class Disposition(StrEnum):
    """What should happen to a blocked issue."""

    #: The recorded blocker is checkable and has demonstrably cleared.
    RELEASE = "release"
    #: The recorded blocker is checkable and still holds.
    HOLD = "hold"
    #: A person's decision. Never cleared by this module.
    OWNER_GATE = "owner-gate"
    #: Explicitly parked by the issue itself.
    PARKED = "parked"
    #: No checkable record. Held, and reported so it stops being invisible.
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True)
class Reconciliation:
    """One issue's disposition and the reason for it."""

    issue_number: int
    disposition: Disposition
    reason: str
    blocker: str | None = None

    @property
    def releases(self) -> bool:
        return self.disposition is Disposition.RELEASE

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": "oc.blocked-reconciliation.v1",
            "issue_number": self.issue_number,
            "disposition": str(self.disposition),
            "reason": self.reason,
            "blocker": self.blocker,
            # Stated rather than implied: a caller must not infer permission to
            # relabel from anything but this.
            "release_authorized": self.releases,
        }


@dataclass
class WorldState:
    """What the caller knows about the things issues say block them.

    Deliberately explicit. A missing entry means "not known", which holds the
    issue — it never reads as "cleared", because absence of evidence that a
    blocker still stands is not evidence that it lifted.
    """

    closed_issues: set[int] = field(default_factory=set)
    open_issues: set[int] = field(default_factory=set)
    merged_prs: set[int] = field(default_factory=set)
    unmerged_prs: set[int] = field(default_factory=set)


def _labels(issue: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for label in issue.get("labels") or []:
        name = label if isinstance(label, str) else label.get("name")
        if name:
            names.add(str(name))
    return names


def _blocker_text(issue: dict[str, Any]) -> str:
    """The issue body plus its comments, which is where the record may live.

    ``comments`` is an integer count in GitHub's issue *listing* and a list of
    objects when fetched per issue. Both shapes reach this module, and a caller
    that passes the listing must not get a crash — it must get "no record
    found", which holds the issue. Reading a count as a body would be the worse
    outcome: the blocker is then unreadable and the issue looks decidable.
    """
    parts = [str(issue.get("body") or "")]
    comments = issue.get("comments")
    if isinstance(comments, (list, tuple)):
        for comment in comments:
            if isinstance(comment, dict):
                parts.append(str(comment.get("body") or ""))
            elif isinstance(comment, str):
                parts.append(comment)
    return "\n".join(parts)


def reconcile_issue(issue: dict[str, Any], world: WorldState) -> Reconciliation:
    """Decide one issue, checking the blocker it actually recorded."""
    number = int(issue.get("number") or 0)
    text = _blocker_text(issue)
    labels = _labels(issue)

    if NO_REQUEUE.search(text):
        return Reconciliation(
            number,
            Disposition.PARKED,
            "the issue declares OC-AUTO-REQUEUE: false, which is a deliberate park",
        )

    if OWNER_GATE in labels or "blocked-on-owner" in labels:
        return Reconciliation(
            number,
            Disposition.OWNER_GATE,
            "labelled as waiting on the owner; not this module's to clear",
        )

    match = BLOCKED_ON.search(text)
    if not match:
        return Reconciliation(
            number,
            Disposition.UNVERIFIABLE,
            (
                "no OC-BLOCKED-ON record, so the blocker cannot be checked. Held. "
                "Add one to the BLOCKED comment and this becomes decidable"
            ),
        )

    ref = match.group("ref")
    lowered = ref.lower()

    if lowered in OWNER_FORMS:
        return Reconciliation(
            number,
            Disposition.OWNER_GATE,
            f"blocked on {lowered}, which is a person's decision",
            blocker=ref,
        )

    issue_match = ISSUE_REF.match(ref)
    if issue_match:
        target = int(issue_match.group("number"))
        if target in world.closed_issues:
            return Reconciliation(
                number,
                Disposition.RELEASE,
                f"blocked on #{target}, which is closed",
                blocker=ref,
            )
        if target in world.open_issues:
            return Reconciliation(
                number, Disposition.HOLD, f"#{target} is still open", blocker=ref
            )
        return Reconciliation(
            number,
            Disposition.HOLD,
            f"the state of #{target} is not known, which is not the same as cleared",
            blocker=ref,
        )

    pr_match = PR_REF.match(ref)
    if pr_match:
        target = int(pr_match.group("number"))
        if target in world.merged_prs:
            return Reconciliation(
                number,
                Disposition.RELEASE,
                f"blocked on PR #{target}, which is merged",
                blocker=ref,
            )
        if target in world.unmerged_prs:
            return Reconciliation(
                number, Disposition.HOLD, f"PR #{target} is not merged", blocker=ref
            )
        return Reconciliation(
            number,
            Disposition.HOLD,
            f"the state of PR #{target} is not known, which is not the same as cleared",
            blocker=ref,
        )

    return Reconciliation(
        number,
        Disposition.UNVERIFIABLE,
        f"blocker {ref!r} is not a form this module can check. Held",
        blocker=ref,
    )


def reconcile(issues: list[dict[str, Any]], world: WorldState) -> list[Reconciliation]:
    """Decide every blocked issue. Issues without the label are not this module's."""
    out: list[Reconciliation] = []
    for issue in issues:
        if str(issue.get("state") or "OPEN").upper() != "OPEN":
            continue
        if BLOCKED not in _labels(issue):
            continue
        out.append(reconcile_issue(issue, world))
    return sorted(out, key=lambda r: r.issue_number)


def to_report(results: list[Reconciliation]) -> dict[str, Any]:
    """A report a person can read and a workflow can act on."""
    counts: dict[str, int] = {str(d): 0 for d in Disposition}
    for result in results:
        counts[str(result.disposition)] += 1
    return {
        "schema": "oc.blocked-reconciliation-report.v1",
        "examined": len(results),
        "counts": counts,
        "release_numbers": [r.issue_number for r in results if r.releases],
        "results": [r.to_record() for r in results],
        # Said out loud because the number is the point: every one of these is
        # work the portfolio cannot see and no mechanism will ever look at again.
        "unverifiable_numbers": [
            r.issue_number for r in results if r.disposition is Disposition.UNVERIFIABLE
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues-json", required=True, help="path to the issue list")
    parser.add_argument("--world-json", required=True, help="path to the known state")
    args = parser.parse_args(argv)

    with open(args.issues_json, encoding="utf-8") as handle:
        issues = json.load(handle)
    with open(args.world_json, encoding="utf-8") as handle:
        raw = json.load(handle)

    world = WorldState(
        closed_issues=set(raw.get("closed_issues") or []),
        open_issues=set(raw.get("open_issues") or []),
        merged_prs=set(raw.get("merged_prs") or []),
        unmerged_prs=set(raw.get("unmerged_prs") or []),
    )
    json.dump(to_report(reconcile(issues, world)), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
