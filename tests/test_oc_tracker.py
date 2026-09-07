"""Behavioural contract for the OC durable tracker rotation module.

Tests exercise scripts/oc_tracker.py directly via importlib (same pattern as
test_oc_portfolio_scheduler.py) so the policy is provable without running gh.

Seven safety scenarios:
1. Normal write → posted to configured tracker, returns issue number
2. TRACKER_EXHAUSTED → rotation triggered, successor created, comment posted there
3. Existing successor found (idempotent) → reuses existing successor, no new issue
4. Auth/permission error → TrackerAuthError raised, no silent recovery
5. Active tracker found via oc-active-tracker label → uses labelled issue, not configured
6. Concurrent rotation (successor already on re-check) → idempotent, single issue used
7. Rotation succeeds but successor write fails (auth) → TrackerAuthError propagated
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Callable

import pytest

SCRIPT = Path("scripts/oc_tracker.py")
_spec = importlib.util.spec_from_file_location("oc_tracker", SCRIPT)
ot = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ot)

REPO = "jsp1440/orchid-calyx-backend"
TRACKER = 1031
SUCCESSOR = 1100
BODY = "ORCHID CONTINUOUS ENGINE — dispatch receipt for issues 42,99."


# ---------------------------------------------------------------------------
# Mock builder helpers
# ---------------------------------------------------------------------------


def _ok(stdout: str = "") -> tuple[int, str, str]:
    return (0, stdout, "")


def _err(stderr: str, rc: int = 1) -> tuple[int, str, str]:
    return (rc, "", stderr)


def _exhausted() -> tuple[int, str, str]:
    return _err("GraphQL: Commenting is disabled on issues with more than 2500 comments (addComment)")


def _auth_err() -> tuple[int, str, str]:
    return _err("HTTP 403: Resource not accessible by personal access token")


def _no_active_trackers() -> tuple[int, str, str]:
    return _ok("[]")


def _active_tracker(issue_num: int) -> tuple[int, str, str]:
    return _ok(json.dumps([{"number": issue_num}]))


def _successor_created(issue_num: int) -> tuple[int, str, str]:
    return _ok(json.dumps({"number": issue_num}))


def _no_successor_comments() -> tuple[int, str, str]:
    # gh api returns empty when no matching comments
    return _ok("")


def _successor_comment_exists(exhausted: int, successor: int) -> tuple[int, str, str]:
    body = ot._serialize_successor(exhausted, successor)
    # jq outputs the body as a JSON-encoded string
    return _ok(json.dumps(body))


# ---------------------------------------------------------------------------
# Scenario 1: Normal write — posted to configured tracker
# ---------------------------------------------------------------------------


def test_normal_write_posts_to_configured_tracker() -> None:
    """When tracker is healthy, comment goes to configured_tracker and that number is returned."""
    calls: list[tuple] = []

    def mock_run(*args: str) -> tuple[int, str, str]:
        calls.append(args)
        if args[0] == "issue" and args[1] == "list":
            return _no_active_trackers()
        if args[0] == "issue" and args[1] == "comment":
            return _ok()
        return _ok()

    result = ot.post_tracker_comment(REPO, TRACKER, BODY, _run=mock_run)

    assert result == TRACKER
    comment_calls = [c for c in calls if c[0] == "issue" and c[1] == "comment"]
    assert len(comment_calls) == 1
    assert str(TRACKER) in comment_calls[0]


# ---------------------------------------------------------------------------
# Scenario 2: TRACKER_EXHAUSTED — rotation creates successor, posts there
# ---------------------------------------------------------------------------


def test_exhausted_tracker_rotates_and_posts_to_successor() -> None:
    """When tracker hits 2500-comment ceiling, a successor is created and used."""
    created: list[int] = []
    posted_to: list[int] = []

    def mock_run(*args: str) -> tuple[int, str, str]:
        # find_active_tracker: no label-based successor yet
        if args[0] == "issue" and args[1] == "list" and "--label" in args:
            return _no_active_trackers()
        # First comment attempt: exhausted
        if args[0] == "issue" and args[1] == "comment" and args[2] == str(TRACKER):
            posted_to.append(TRACKER)
            return _exhausted()
        # _find_existing_successor: no prior record
        if args[0] == "api" and "comments" in args[2]:
            return _no_successor_comments()
        # _create_successor_issue
        if args[0] == "issue" and args[1] == "create":
            created.append(SUCCESSOR)
            return _successor_created(SUCCESSOR)
        # Post successor marker on exhausted issue (best-effort)
        if args[0] == "issue" and args[1] == "comment" and args[2] == str(TRACKER):
            return _ok()
        # Post actual body to successor
        if args[0] == "issue" and args[1] == "comment" and args[2] == str(SUCCESSOR):
            posted_to.append(SUCCESSOR)
            return _ok()
        return _ok()

    result = ot.post_tracker_comment(REPO, TRACKER, BODY, _run=mock_run)

    assert result == SUCCESSOR
    assert SUCCESSOR in created
    assert SUCCESSOR in posted_to


# ---------------------------------------------------------------------------
# Scenario 3: Existing successor found — idempotent, no new issue created
# ---------------------------------------------------------------------------


def test_existing_successor_reused_not_duplicated() -> None:
    """When a successor record already exists on the exhausted issue, reuse it."""
    create_calls: list[str] = []

    def mock_run(*args: str) -> tuple[int, str, str]:
        if args[0] == "issue" and args[1] == "list":
            return _no_active_trackers()
        if args[0] == "issue" and args[1] == "comment" and args[2] == str(TRACKER):
            return _exhausted()
        # _find_existing_successor: returns existing record
        if args[0] == "api" and "comments" in args[2]:
            return _successor_comment_exists(TRACKER, SUCCESSOR)
        if args[0] == "issue" and args[1] == "create":
            create_calls.append("created")
            return _successor_created(SUCCESSOR + 1)  # would be wrong number
        if args[0] == "issue" and args[1] == "comment" and args[2] == str(SUCCESSOR):
            return _ok()
        return _ok()

    result = ot.post_tracker_comment(REPO, TRACKER, BODY, _run=mock_run)

    assert result == SUCCESSOR
    assert create_calls == [], "No new issue should be created when successor already exists"


# ---------------------------------------------------------------------------
# Scenario 4: Auth/permission error — fail closed, TrackerAuthError raised
# ---------------------------------------------------------------------------


def test_auth_error_raises_tracker_auth_error_and_does_not_rotate() -> None:
    """HTTP 403/permission errors must not trigger rotation — fail closed."""
    rotate_calls: list[str] = []

    def mock_run(*args: str) -> tuple[int, str, str]:
        if args[0] == "issue" and args[1] == "list":
            return _no_active_trackers()
        if args[0] == "issue" and args[1] == "comment":
            return _auth_err()
        if args[0] == "issue" and args[1] == "create":
            rotate_calls.append("rotated")
            return _successor_created(SUCCESSOR)
        return _ok()

    with pytest.raises(ot.TrackerAuthError):
        ot.post_tracker_comment(REPO, TRACKER, BODY, _run=mock_run)

    assert rotate_calls == [], "Auth errors must not trigger rotation"


# ---------------------------------------------------------------------------
# Scenario 5: Active tracker discovered via oc-active-tracker label
# ---------------------------------------------------------------------------


def test_active_tracker_label_redirects_to_successor() -> None:
    """When oc-active-tracker label exists on a different issue, use that issue."""
    comment_targets: list[str] = []

    def mock_run(*args: str) -> tuple[int, str, str]:
        if args[0] == "issue" and args[1] == "list" and "--label" in args:
            return _active_tracker(SUCCESSOR)
        if args[0] == "issue" and args[1] == "comment":
            comment_targets.append(args[2])
            return _ok()
        return _ok()

    result = ot.post_tracker_comment(REPO, TRACKER, BODY, _run=mock_run)

    assert result == SUCCESSOR
    assert str(SUCCESSOR) in comment_targets
    assert str(TRACKER) not in comment_targets


# ---------------------------------------------------------------------------
# Scenario 6: Concurrent rotation — successor created by another run, idempotent
# ---------------------------------------------------------------------------


def test_concurrent_rotation_is_idempotent() -> None:
    """If another process created a successor between exhaustion detection and rotation,
    the pre-check in _rotate_tracker must find it and return it without creating another.
    """
    create_calls: list[str] = []

    def mock_run(*args: str) -> tuple[int, str, str]:
        if args[0] == "issue" and args[1] == "list":
            return _no_active_trackers()
        if args[0] == "issue" and args[1] == "comment" and args[2] == str(TRACKER):
            return _exhausted()
        # Simulate: by the time we check, another process already wrote the successor record
        if args[0] == "api" and "comments" in args[2]:
            return _successor_comment_exists(TRACKER, SUCCESSOR)
        if args[0] == "issue" and args[1] == "create":
            create_calls.append("created")
            return _successor_created(SUCCESSOR + 99)
        if args[0] == "issue" and args[1] == "comment" and args[2] == str(SUCCESSOR):
            return _ok()
        return _ok()

    result = ot.post_tracker_comment(REPO, TRACKER, BODY, _run=mock_run)

    assert result == SUCCESSOR
    assert create_calls == [], "Concurrent rotation must not create a second successor"


# ---------------------------------------------------------------------------
# Scenario 7: Successor write fails with auth — TrackerAuthError propagated
# ---------------------------------------------------------------------------


def test_successor_write_auth_failure_propagates_not_silenced() -> None:
    """If posting to the newly-created successor fails with auth, TrackerAuthError must
    propagate — not be silently swallowed.
    """

    def mock_run(*args: str) -> tuple[int, str, str]:
        if args[0] == "issue" and args[1] == "list":
            return _no_active_trackers()
        # First comment: exhausted
        if args[0] == "issue" and args[1] == "comment" and args[2] == str(TRACKER):
            return _exhausted()
        # No prior successor record
        if args[0] == "api" and "comments" in args[2]:
            return _no_successor_comments()
        # Successor created successfully
        if args[0] == "issue" and args[1] == "create":
            return _successor_created(SUCCESSOR)
        # Successor marker write on old issue: exhausted (OK — best-effort)
        # Actual body write on successor: auth error
        if args[0] == "issue" and args[1] == "comment" and args[2] == str(SUCCESSOR):
            return _auth_err()
        return _ok()

    with pytest.raises(ot.TrackerAuthError, match="Auth error posting to successor"):
        ot.post_tracker_comment(REPO, TRACKER, BODY, _run=mock_run)


# ---------------------------------------------------------------------------
# _classify_error unit tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stderr",
    [
        "GraphQL: Commenting is disabled on issues with more than 2500 comments (addComment)",
        "failed: 2500 comment limit reached",
        "Commenting is disabled on this issue",
    ],
)
def test_classify_error_exhausted(stderr: str) -> None:
    assert ot._classify_error(stderr) is ot.TrackerExhausted


@pytest.mark.parametrize(
    "stderr",
    [
        "HTTP 403: Resource not accessible by personal access token",
        "HTTP 401: authentication required",
        "Permission denied",
        "Must have push access",
    ],
)
def test_classify_error_auth(stderr: str) -> None:
    assert ot._classify_error(stderr) is ot.TrackerAuthError


def test_classify_error_unknown_returns_none() -> None:
    assert ot._classify_error("something completely unexpected") is None


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


def test_successor_record_round_trips() -> None:
    body = ot._serialize_successor(TRACKER, SUCCESSOR)
    assert f"<!-- {ot.TRACKER_SUCCESSOR_TAG}" in body
    result = ot._parse_successor_comment(body)
    assert result == SUCCESSOR


def test_parse_successor_comment_returns_none_on_missing_tag() -> None:
    assert ot._parse_successor_comment("No tracker data here.") is None


def test_parse_successor_comment_returns_none_on_malformed_json() -> None:
    body = f"<!-- {ot.TRACKER_SUCCESSOR_TAG}\n{{broken\n-->"
    assert ot._parse_successor_comment(body) is None
