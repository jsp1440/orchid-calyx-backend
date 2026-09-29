from __future__ import annotations

import copy

import pytest

from scripts.oc_blocked_snapshot_enrich import enrich_snapshot
from scripts.oc_swarm_controller import blocked_reconciliation_report


class FakeTransport:
    repository = "jsp1440/orchid-continuum-frontend"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.issue_number = 20

    def issue_comments(self, number: int) -> list[dict]:
        self.calls.append(("issue_comments", number))
        return [
            {
                "id": 100,
                "body": "Blocked pending repair.\nOC-BLOCKED-ON: pr#30",
                "user": {"login": "github-actions[bot]"},
            }
        ]

    def issue(self, number: int) -> dict:
        self.calls.append(("issue_state", number))
        return {"number": self.issue_number, "state": "CLOSED", "url": f"issue://{number}"}

    def pull_request(self, number: int) -> dict:
        self.calls.append(("pull_request_state", number))
        return {
            "number": number,
            "state": "MERGED",
            "mergedAt": "2026-09-19T00:00:00Z",
            "url": f"pr://{number}",
        }


def snapshot() -> dict:
    return {
        "issues": [
            {
                "number": 7,
                "state": "OPEN",
                "labels": ["oc-blocked"],
                "body": "",
                "comments": 1,
            }
        ],
        "pull_requests": [],
    }


def report(*requests: tuple[str, int]) -> dict:
    return {
        "observation_requests": [
            {"kind": kind, "number": number} for kind, number in requests
        ]
    }


def test_comments_then_pr_state_make_the_release_decidable_across_cycles() -> None:
    transport = FakeTransport()
    first = enrich_snapshot(transport, snapshot(), report(("issue_comments", 7)))
    first_report = blocked_reconciliation_report(first)
    assert first_report["release_plan"]["action_count"] == 0
    assert first_report["observation_requests"] == [
        {"kind": "pull_request_state", "number": 30}
    ]

    second = enrich_snapshot(
        transport,
        first,
        {"observation_requests": first_report["observation_requests"]},
    )
    second_report = blocked_reconciliation_report(second)
    assert second_report["observation_requests"] == []
    assert second_report["release_plan"]["action_count"] == 1
    assert second_report["release_plan"]["actions"][0]["issue_number"] == 7
    assert transport.calls == [("issue_comments", 7), ("pull_request_state", 30)]


def test_restart_reuses_persisted_observations_without_fetching_again() -> None:
    transport = FakeTransport()
    request = report(("issue_comments", 7), ("pull_request_state", 30))
    first = enrich_snapshot(transport, snapshot(), request)
    calls_after_first = list(transport.calls)
    second = enrich_snapshot(transport, first, request)

    assert transport.calls == calls_after_first
    expected = copy.deepcopy(first)
    expected["blocked_enrichment"]["fetched"] = []
    expected["blocked_enrichment"]["reused"] = request["observation_requests"]
    assert second == expected
    assert second["blocked_enrichment"]["complete"] is True


def test_repository_identity_change_is_rejected_before_any_fetch() -> None:
    transport = FakeTransport()
    original = snapshot()
    original["repository"] = "jsp1440/a-different-repository"
    with pytest.raises(ValueError, match="repository identity"):
        enrich_snapshot(transport, original, report(("issue_comments", 7)))
    assert transport.calls == []


def test_mismatched_observation_identity_is_recorded_and_not_persisted() -> None:
    transport = FakeTransport()
    transport.issue_number = 999
    enriched = enrich_snapshot(transport, snapshot(), report(("issue_state", 20)))

    assert enriched["blocked_enrichment"]["complete"] is False
    assert enriched["blocked_enrichment"]["errors"] == [
        {
            "kind": "issue_state",
            "number": 20,
            "reason": "observation_unconfirmed",
            "error_type": "ValueError",
        }
    ]
    assert all(issue["number"] != 20 for issue in enriched["issues"])


def test_owner_gate_discovered_in_comments_can_never_make_a_release_action() -> None:
    class OwnerTransport(FakeTransport):
        def issue_comments(self, number: int) -> list[dict]:
            self.calls.append(("issue_comments", number))
            return [{"id": 1, "body": "OC-BLOCKED-ON: deployment", "user": {"login": "bot"}}]

    enriched = enrich_snapshot(OwnerTransport(), snapshot(), report(("issue_comments", 7)))
    decision = blocked_reconciliation_report(enriched)
    assert decision["results"][0]["disposition"] == "owner-gate"
    assert decision["release_plan"]["action_count"] == 0


@pytest.mark.parametrize(
    "bad_report",
    [
        {},
        {"observation_requests": [{"kind": "unknown", "number": 1}]},
        {"observation_requests": [{"kind": "issue_state", "number": 0}]},
        report(("issue_state", 1), ("issue_state", 1)),
    ],
)
def test_unbounded_or_malformed_request_lists_fail_before_fetch(bad_report: dict) -> None:
    transport = FakeTransport()
    with pytest.raises(ValueError):
        enrich_snapshot(transport, snapshot(), bad_report)
    assert transport.calls == []
