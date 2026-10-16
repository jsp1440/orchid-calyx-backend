"""One owner comment on #1924 can enroll a bounded batch of owner-opened issues.

The standing grant is a fallback: a per-issue record, when present, decides
alone. Either kind of record counts only when the owner typed it directly,
never when an agent posted it with the owner's token.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts import oc_hosted_completion as hosted
from scripts import oc_paid_issue_admission as admission

REPO = "jsp1440/orchid-calyx-backend"
NOW = datetime(2026, 10, 16, tzinfo=UTC)
STANDING_ID = 7000000001
APP = {"id": 1, "slug": "claude", "name": "Claude"}


def _issue(number=1930, **overrides):
    issue = {
        "number": number,
        "state": "open",
        "title": f"Bounded fix {number}",
        "body": (
            "Fix the report.\n\n"
            "Allowed paths:\n"
            "- `runtime/bottlenecks.py`\n"
            "- `tests/test_runtime_bottlenecks.py`\n"
        ),
        "user": {"login": "jsp1440"},
        "author_association": "OWNER",
        "labels": [{"name": "oc-queued"}],
    }
    issue.update(overrides)
    return issue


def _standing(**overrides):
    payload = {
        "repository": REPO,
        "target": hosted.BRANCH,
        "risk": "low",
        "first_issue": 1925,
        "last_issue": 1974,
        "expires_at": "2026-11-10T00:00:00Z",
    }
    payload.update(overrides)
    return {
        "id": STANDING_ID,
        "user": {"login": "jsp1440"},
        "author_association": "OWNER",
        "performed_via_github_app": None,
        "created_at": "2026-10-15T00:00:00Z",
        "updated_at": "2026-10-15T00:00:00Z",
        "body": "Standing grant.\n" + hosted.tagged(hosted.STANDING_TAG, payload),
    }


def _per_issue(issue, **overrides):
    grant = {
        "repository": REPO,
        "issue": issue["number"],
        "issue_material": hosted.issue_material(issue),
        "target": hosted.BRANCH,
        "checker_calls": 1,
        "risk": "moderate",
        "allowed_paths": ["runtime/other.py", "tests/test_other.py"],
        "expires_at": "2026-10-18T00:00:00Z",
    }
    grant.update(overrides)
    return {
        "id": 6100000000 + issue["number"],
        "user": {"login": "jsp1440"},
        "author_association": "OWNER",
        "performed_via_github_app": None,
        "created_at": "2026-10-15T03:00:00Z",
        "updated_at": "2026-10-15T03:00:00Z",
        "body": hosted.tagged(hosted.AUTH_TAG, grant),
    }


def _grant(issue, comments=(), standing=None):
    return hosted.authorization(
        issue,
        list(comments),
        REPO,
        NOW,
        standing_comments=[_standing()] if standing is None else standing,
    )


def _refusal(issue, comments=(), standing=None):
    with pytest.raises(ValueError) as caught:
        _grant(issue, comments, standing)
    return str(caught.value)


def test_a_valid_standing_grant_enrolls_an_owner_issue_in_range():
    issue = _issue()
    grant = _grant(issue)
    assert grant["comment_id"] == STANDING_ID
    assert grant["issue"] == 1930
    assert grant["issue_material"] == hosted.issue_material(issue)
    assert grant["checker_calls"] == 1
    assert grant["risk"] == "low"
    assert grant["target"] == hosted.BRANCH
    assert grant["allowed_paths"] == [
        "runtime/bottlenecks.py",
        "tests/test_runtime_bottlenecks.py",
    ]
    assert grant["expires_at"] == "2026-11-10T00:00:00Z"
    # Deterministic, so prepare/reserve/record compare equal grants.
    assert grant == _grant(_issue())


def test_both_ends_of_the_range_are_covered():
    assert _grant(_issue(1925))["issue"] == 1925
    assert _grant(_issue(1974))["issue"] == 1974


def test_the_grant_pins_the_issue_material():
    issue = _issue()
    grant = _grant(issue)
    issue["body"] += "\nAlso change something else."
    assert hosted.issue_material(issue) != grant["issue_material"]


def test_a_per_issue_record_decides_alone():
    issue = _issue()
    grant = _grant(issue, [_per_issue(issue)])
    assert grant["comment_id"] == 6100001930
    assert grant["risk"] == "moderate"
    # An invalid per-issue record is not rescued by the standing grant.
    stale = _per_issue(issue, expires_at="2026-10-01T00:00:00Z")
    assert _refusal(issue, [stale]) == "authorization_expired"


def test_without_standing_comments_the_per_issue_rule_is_unchanged():
    with pytest.raises(ValueError, match="hosted_authorization_missing"):
        hosted.authorization(_issue(), [], REPO, NOW)


def test_an_app_posted_standing_grant_is_refused():
    posted = _standing()
    posted["performed_via_github_app"] = APP
    assert _refusal(_issue(), standing=[posted]) == "authorization_posted_by_app"


def test_an_app_posted_per_issue_record_is_refused():
    issue = _issue()
    record = _per_issue(issue)
    record["performed_via_github_app"] = APP
    assert _refusal(issue, [record]) == "authorization_posted_by_app"


def test_a_standing_grant_by_someone_else_or_edited_is_refused():
    other = _standing()
    other["user"] = {"login": "github-actions[bot]"}
    other["author_association"] = "NONE"
    assert _refusal(_issue(), standing=[other]) == "authorization_not_owner"
    edited = _standing()
    edited["updated_at"] = "2026-10-15T01:00:00Z"
    assert _refusal(_issue(), standing=[edited]) == "authorization_edited"


def test_missing_or_duplicate_standing_grants_are_refused():
    missing = "hosted_authorization_missing_or_ambiguous"
    assert _refusal(_issue(), standing=[]) == missing
    assert _refusal(_issue(), standing=[_standing(), _standing()]) == missing


@pytest.mark.parametrize("number", [1924, 1975, 2100])
def test_an_issue_outside_the_range_is_refused(number):
    assert _refusal(_issue(number)) == "issue_outside_standing_range"


def test_an_expired_standing_grant_is_refused():
    standing = [_standing(expires_at="2026-10-15T12:00:00Z")]
    assert _refusal(_issue(), standing=standing) == "authorization_expired"


def test_a_standing_grant_longer_than_31_days_is_refused():
    standing = [_standing(expires_at="2026-11-15T00:00:01Z")]
    assert _refusal(_issue(), standing=standing) == "standing_authorization_too_long"
    exact = [_standing(expires_at="2026-11-15T00:00:00Z")]
    assert _grant(_issue(), standing=exact)["comment_id"] == STANDING_ID


def test_a_range_wider_than_50_issues_is_refused():
    standing = [_standing(first_issue=1925, last_issue=1975)]
    assert _refusal(_issue(), standing=standing) == "standing_authorization_invalid"


@pytest.mark.parametrize(
    "overrides",
    [
        {"risk": "moderate"},
        {"risk": "high"},
        {"target": "main"},
        {"repository": "someone/else"},
        {"first_issue": 1980, "last_issue": 1925},
        {"first_issue": "1925"},
        {"checker_calls": 5},
        {"allowed_paths": ["runtime/x.py"]},
    ],
)
def test_wrong_risk_target_or_fields_are_refused(overrides):
    standing = [_standing(**overrides)]
    assert _refusal(_issue(), standing=standing) == "standing_authorization_invalid"


def test_an_issue_not_opened_by_the_owner_is_refused():
    issue = _issue(user={"login": "someone"}, author_association="CONTRIBUTOR")
    assert _refusal(issue) == "issue_not_opened_by_owner"


def test_a_closed_issue_is_refused():
    assert _refusal(_issue(state="closed")) == "issue_not_open"


@pytest.mark.parametrize(
    "body",
    [
        "No declaration at all.",
        "Allowed paths: `scripts/oc_hosted_completion.py`, `tests/test_x.py`",
        "Allowed paths: `app/main.py`",
        "Allowed paths: `migrations/001.sql`",
        "Allowed paths: `../outside.py`",
        "Allowed paths: `runtime/a.py`\nAllowed paths: `runtime/b.py`",
    ],
)
def test_protected_or_missing_paths_are_refused(body):
    assert _refusal(_issue(body=body)) == "unsafe_allowed_paths"


def _attempt(authorization):
    return {
        "user": {"login": "github-actions[bot]"},
        "created_at": "2026-10-16T00:00:00Z",
        "updated_at": "2026-10-16T00:00:00Z",
        "body": hosted.tagged(hosted.ATTEMPT_TAG, {"authorization": authorization}),
    }


def test_each_issue_still_gets_exactly_one_checker_call():
    first, second = _issue(1930), _issue(1931)
    first_grant, second_grant = _grant(first), _grant(second)
    assert first_grant["comment_id"] == second_grant["comment_id"] == STANDING_ID
    # Attempt records live on each issue's own comments.
    first_comments = [_attempt(STANDING_ID)]
    assert hosted.checker_attempt_reserved(first_grant, first_comments)
    assert not hosted.checker_attempt_reserved(second_grant, [])
    # The spent attempt on the first issue is not a standing grant record, and
    # still counts after the grant is re-read from that issue's comments.
    assert hosted.checker_attempt_reserved(
        _grant(first, first_comments), first_comments
    )


def _admit(issue, comments, standing):
    return admission.admit(
        REPO,
        issue["number"],
        fetch=lambda *_: (issue, comments, standing),
        now=NOW,
    )


def test_paid_admission_accepts_the_standing_grant():
    decision = _admit(_issue(), [], [_standing()])
    assert decision["authorized"] is True
    assert decision["authorization_comment"] == STANDING_ID
    assert decision["expires_at"] == "2026-11-10T00:00:00Z"


def test_paid_admission_refuses_an_app_posted_standing_grant():
    posted = _standing()
    posted["performed_via_github_app"] = APP
    decision = _admit(_issue(), [], [posted])
    assert decision["authorized"] is False
    assert decision["reason"] == admission.DENIAL
    assert decision["detail"] == "authorization_posted_by_app"


def test_paid_admission_fetches_the_standing_issue(monkeypatch):
    calls = []

    def fake_pages(repository, path, field=None):
        calls.append(path)
        return []

    monkeypatch.setattr(hosted, "api", lambda repository, path: _issue())
    monkeypatch.setattr(hosted, "pages", fake_pages)
    _issue_row, _comments, standing = admission._fetch(REPO, 1930)
    assert standing == []
    assert f"issues/{hosted.STANDING_ISSUE}/comments" in calls
