"""Efficiency metrics come only from durable receipts, never estimates."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts import oc_efficiency_report as eff

START = datetime(2026, 10, 16, 6, 0, tzinfo=timezone.utc)
END = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
BOT = {"login": "github-actions[bot]"}
REPOSITORY = "jsp1440/orchid-calyx-backend"
HEAD = "a" * 40
MERGE = "b" * 40


def c(cid, body, at="2026-10-16T07:00:00Z", user=BOT):
    return {"id": cid, "body": body, "user": user, "created_at": at}


def receipt(run, issue, provider, reserved, actual="unknown"):
    return (
        f"[OC-GOVERNOR-COST] run_id={run} issue={issue} provider={provider} "
        f"reserved_usd={reserved} actual_usd={actual} date=2026-10-16 month=2026-10"
    )


def test_spend_uses_actual_then_bot_settlement_then_reservation():
    comments = [
        c(1, receipt(10, 1, "anthropic", "0.50", "0.0400")),
        c(2, receipt(11, 1, "anthropic-checker", "0.08")),
        c(
            3,
            "[OC-GOVERNOR-COST-SETTLE] run_id=11 provider=anthropic-checker actual_usd=0.0120",
        ),
        c(4, receipt(12, 2, "anthropic-checker", "0.08")),
    ]
    spend = eff.ledger_spend(comments, START, END)
    assert spend["total_counted_usd"] == "0.1320"
    assert spend["by_provider"]["anthropic-checker"]["actual_known"] == 1


def test_non_bot_lines_and_out_of_window_receipts_are_ignored():
    comments = [
        c(1, receipt(10, 1, "anthropic", "0.50", "0.0400"), user={"login": "someone"}),
        c(2, receipt(11, 1, "anthropic", "0.50", "0.0400"), at="2026-10-15T07:00:00Z"),
        c(3, receipt(12, 1, "anthropic-checker", "0.08")),
        c(
            4,
            "[OC-GOVERNOR-COST-SETTLE] run_id=12 provider=anthropic-checker actual_usd=0",
            user={"login": "x"},
        ),
    ]
    spend = eff.ledger_spend(comments, START, END)
    assert spend["total_counted_usd"] == "0.08"
    assert [r["comment_id"] for r in spend["receipts"]] == [3]


def claim(at, run):
    payload = {
        "schema": "oc.swarm-claim.v1",
        "issue_number": 5,
        "lease_id": f"o/r:{run}:1:5",
    }
    return (
        "[OC-SWARM-V4] Dependency/resource lease claimed: `"
        + json.dumps(payload)
        + "`."
    )


def settlement(merge=MERGE, **context_changes):
    context = {
        "repository": REPOSITORY,
        "issue": 5,
        "pr": 9,
        "head": HEAD,
    }
    context.update(context_changes)
    data = {"context": context, "merge_sha": merge}
    return "<!-- OC-HOSTED-SETTLEMENT-V1\n" + json.dumps(data) + "\n-->"


def github_api(responses=None):
    results = {
        f"repos/{REPOSITORY}/pulls/9": {
            "number": 9,
            "merged": True,
            "merge_commit_sha": MERGE,
            "base": {"ref": "oc-autonomous-integration"},
            "head": {"sha": HEAD},
            "body": "OC-AUTO-ISSUE: #5",
            "html_url": f"https://github.com/{REPOSITORY}/pull/9",
        },
        f"repos/{REPOSITORY}/git/commits/{MERGE}": {
            "parents": [{"sha": "c" * 40}, {"sha": HEAD}],
            "html_url": f"https://github.com/{REPOSITORY}/commit/{MERGE}",
        },
        f"repos/{REPOSITORY}/compare/{MERGE}...oc-autonomous-integration": {
            "status": "ahead"
        },
    }
    results.update(responses or {})
    return results.__getitem__


def test_a_cycle_counts_only_a_bot_settlement_with_a_verified_merge():
    comments = [
        c(1, claim("x", 1), at="2026-10-16T07:00:00Z"),
        c(2, eff.RECOVERY_PREFIX + "{}`.", at="2026-10-16T07:02:00Z"),
        c(3, claim("x", 2), at="2026-10-16T07:05:00Z"),
        c(4, settlement(), at="2026-10-16T07:10:00Z"),
    ]
    cycle = eff.issue_cycle(5, comments, START, END, api=github_api())
    assert (
        cycle["claims"] == 2
        and cycle["recoveries"] == 1
        and cycle["first_attempt"] is False
    )
    assert cycle["cycle_minutes"] == 10.0 and cycle["pr"] == 9
    assert cycle["pull_request"] == f"https://github.com/{REPOSITORY}/pull/9"
    assert cycle["merge_commit"] == f"https://github.com/{REPOSITORY}/commit/{MERGE}"


def test_no_merge_or_forged_settlement_is_not_a_completed_task():
    assert eff.issue_cycle(5, [c(1, settlement(merge=""))], START, END) is None
    assert eff.issue_cycle(5, [c(1, settlement(merge="m" * 40))], START, END) is None
    assert (
        eff.issue_cycle(5, [c(1, settlement(), user={"login": "x"})], START, END)
        is None
    )
    assert (
        eff.issue_cycle(5, [c(1, settlement(), at="2026-10-17T00:00:00Z")], START, END)
        is None
    )


@pytest.mark.parametrize(
    ("receipt_context", "api_changes"),
    [
        ({"repository": "other/repo"}, {}),
        ({"issue": 6}, {}),
        ({"head": "d" * 40}, {}),
        ({}, {f"repos/{REPOSITORY}/pulls/9": None}),
        (
            {},
            {
                f"repos/{REPOSITORY}/pulls/9": {
                    **github_api()(f"repos/{REPOSITORY}/pulls/9"),
                    "merged": False,
                }
            },
        ),
        (
            {},
            {
                f"repos/{REPOSITORY}/pulls/9": {
                    **github_api()(f"repos/{REPOSITORY}/pulls/9"),
                    "number": 10,
                }
            },
        ),
        (
            {},
            {
                f"repos/{REPOSITORY}/pulls/9": {
                    **github_api()(f"repos/{REPOSITORY}/pulls/9"),
                    "merge_commit_sha": "d" * 40,
                }
            },
        ),
        (
            {},
            {
                f"repos/{REPOSITORY}/pulls/9": {
                    **github_api()(f"repos/{REPOSITORY}/pulls/9"),
                    "body": "OC-AUTO-ISSUE: #6",
                }
            },
        ),
        (
            {},
            {
                f"repos/{REPOSITORY}/pulls/9": {
                    **github_api()(f"repos/{REPOSITORY}/pulls/9"),
                    "head": {"sha": "d" * 40},
                }
            },
        ),
        (
            {},
            {
                f"repos/{REPOSITORY}/git/commits/{MERGE}": {
                    "parents": [{"sha": "c" * 40}, {"sha": "d" * 40}]
                }
            },
        ),
        (
            {},
            {
                f"repos/{REPOSITORY}/compare/{MERGE}...oc-autonomous-integration": {
                    "status": "diverged"
                }
            },
        ),
    ],
)
def test_unverified_settlement_does_not_count(receipt_context, api_changes):
    comments = [c(1, settlement(**receipt_context))]
    assert eff.issue_cycle(5, comments, START, END, api=github_api(api_changes)) is None
