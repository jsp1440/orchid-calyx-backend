"""The owner's standing grant admits a bounded range of owner-opened issues.

Per-issue records made the owner sign every task; a standing grant replaces
that for a batch without letting the maker authorize itself: only a comment the
owner typed directly counts, never one posted through an app.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from scripts import oc_hosted_completion as hosted
from scripts import oc_paid_issue_admission as admission

REPO = "jsp1440/orchid-calyx-backend"
NOW = datetime(2026, 10, 16, 12, tzinfo=UTC)
BODY = (
    "## Scope\nAllowed paths:\n- `app/archive/parser.py`\n"
    "- `tests/test_archive_parser_bom.py`\n"
)


def _issue(number=1914, **overrides):
    issue = {
        "number": number,
        "state": "open",
        "title": "Strip a leading UTF-8 BOM before parsing archive CSV/JSON/YAML",
        "body": BODY,
        "user": {"login": "jsp1440"},
        "labels": [{"name": "oc-queued"}],
    }
    issue.update(overrides)
    return issue


def _grant(**overrides):
    grant = {
        "repository": REPO,
        "target": hosted.BRANCH,
        "risk": "low",
        "first_issue": 1914,
        "last_issue": 1960,
        "expires_at": "2026-11-15T00:00:00Z",
    }
    grant.update(overrides)
    return grant


def _record(grant=None, **overrides):
    record = {
        "id": 7000000001,
        "user": {"login": "jsp1440"},
        "author_association": "OWNER",
        "performed_via_github_app": None,
        "created_at": "2026-10-16T03:00:00Z",
        "updated_at": "2026-10-16T03:00:00Z",
        "body": "Standing grant.\n\n"
        + hosted.tagged(hosted.STANDING_TAG, grant if grant is not None else _grant()),
    }
    record.update(overrides)
    return record


def _authorize(issue, standing, comments=()):
    return hosted.authorization(issue, list(comments), REPO, NOW, standing)


def test_an_owner_typed_grant_admits_an_owner_opened_issue_in_range():
    grant = _authorize(_issue(), [_record()])
    assert grant["standing"] is True
    assert grant["comment_id"] == 7000000001
    assert grant["issue"] == 1914
    assert grant["risk"] == "low"
    assert grant["checker_calls"] == 1
    assert grant["target"] == hosted.BRANCH
    assert grant["issue_material"] == hosted.issue_material(_issue())
    assert grant["allowed_paths"] == [
        "app/archive/parser.py",
        "tests/test_archive_parser_bom.py",
    ]


def test_a_grant_posted_through_an_app_never_counts():
    """The maker posts with the owner's token through the Claude app."""
    record = _record(performed_via_github_app={"slug": "claude"})
    with pytest.raises(ValueError, match="authorization_not_owner"):
        _authorize(_issue(), [record])


def test_a_per_issue_record_posted_through_an_app_never_counts():
    issue = _issue()
    grant = {
        "repository": REPO,
        "issue": issue["number"],
        "issue_material": hosted.issue_material(issue),
        "target": hosted.BRANCH,
        "checker_calls": 1,
        "risk": "low",
        "allowed_paths": ["app/archive/parser.py"],
        "expires_at": "2026-10-20T00:00:00Z",
    }
    record = _record(
        body=hosted.tagged(hosted.AUTH_TAG, grant),
        performed_via_github_app={"slug": "claude"},
    )
    with pytest.raises(ValueError, match="authorization_not_owner"):
        hosted.authorization(issue, [record], REPO, NOW)
    record["performed_via_github_app"] = None
    assert hosted.authorization(issue, [record], REPO, NOW)["comment_id"] == 7000000001


def test_a_per_issue_record_decides_alone_even_beside_a_standing_grant():
    """An explicit record, valid or not, is never overridden by the grant."""
    issue = _issue()
    broken = _record(body=hosted.tagged(hosted.AUTH_TAG, {"issue": issue["number"]}))
    with pytest.raises(ValueError):
        _authorize(issue, [_record()], comments=[broken])


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (_record(user={"login": "someone-else"}), "authorization_not_owner"),
        (_record(author_association="COLLABORATOR"), "authorization_not_owner"),
        (_record(updated_at="2026-10-16T04:00:00Z"), "authorization_edited"),
        (_record(_grant(risk="moderate")), "standing_authorization_invalid"),
        (_record(_grant(target="main")), "standing_authorization_invalid"),
        (_record(_grant(repository="other/repo")), "standing_authorization_invalid"),
        (_record(_grant(last_issue=1914 + 50)), "standing_authorization_invalid"),
        (
            _record(_grant(first_issue=1920, last_issue=1919)),
            "standing_authorization_invalid",
        ),
        (_record(_grant(first_issue=True)), "standing_authorization_invalid"),
        (_record(_grant(checker_calls=5)), "standing_authorization_invalid"),
        (
            _record(_grant(expires_at="2026-11-17T03:00:01Z")),
            "standing_authorization_invalid",
        ),
        (_record(_grant(expires_at="2026-10-16T00:00:00Z")), "authorization_expired"),
        (_record(_grant(first_issue=1915)), "issue_outside_standing_authorization"),
    ],
)
def test_every_invalid_or_stale_grant_is_refused(record, reason):
    with pytest.raises(ValueError, match=reason):
        _authorize(_issue(), [record])


def test_a_missing_or_duplicated_grant_is_refused():
    with pytest.raises(ValueError, match="standing_authorization_missing_or_ambiguous"):
        _authorize(_issue(), [])
    with pytest.raises(ValueError, match="standing_authorization_missing_or_ambiguous"):
        _authorize(_issue(), [_record(), _record(id=7000000002)])


def test_an_issue_not_opened_by_the_owner_is_refused():
    with pytest.raises(ValueError, match="issue_not_owner_opened"):
        _authorize(_issue(user={"login": "drive-by"}), [_record()])


@pytest.mark.parametrize(
    "body",
    [
        "No scope section at all.\n",
        "Allowed paths:\n- `.github/workflows/orchid-completion-lane.yml`\n",
        "Allowed paths:\n- `scripts/oc_hosted_completion.py`\n",
        "Allowed paths: `a.py`\n\nAllowed paths: `b.py`\n",
    ],
)
def test_issue_paths_must_be_declared_once_and_unprotected(body):
    with pytest.raises(ValueError, match="unsafe_allowed_paths"):
        _authorize(_issue(body=body), [_record()])


def test_an_edit_after_admission_changes_the_pinned_grant():
    """Later phases compare grants, so an edited issue fails closed."""
    before = _authorize(_issue(), [_record()])
    after = _authorize(
        _issue(body=BODY + "\nAlso rewrite the governor.\n"), [_record()]
    )
    assert before != after
    assert before["issue_material"] != after["issue_material"]


def test_each_issue_gets_one_checker_call_under_the_grant():
    grant = _authorize(_issue(), [_record()])
    attempt = {
        "user": {"login": "github-actions[bot]"},
        "created_at": "2026-10-16T05:00:00Z",
        "updated_at": "2026-10-16T05:00:00Z",
        "body": hosted.tagged(
            hosted.ATTEMPT_TAG, {"authorization": grant["comment_id"]}
        ),
    }
    assert hosted.checker_attempt_reserved(grant, []) is False
    assert hosted.checker_attempt_reserved(grant, [attempt]) is True


def test_paid_admission_accepts_the_standing_grant():
    issue = _issue()
    decision = admission.admit(
        REPO, issue["number"], fetch=lambda *_: (issue, [], [_record()]), now=NOW
    )
    assert decision["authorized"] is True
    assert decision["standing"] is True
    assert decision["authorization_comment"] == 7000000001


def test_paid_admission_refuses_an_app_posted_grant():
    issue = _issue()
    record = copy.deepcopy(_record())
    record["performed_via_github_app"] = {"slug": "claude"}
    decision = admission.admit(
        REPO, issue["number"], fetch=lambda *_: (issue, [], [record]), now=NOW
    )
    assert decision["authorized"] is False
    assert decision["detail"] == "authorization_not_owner"


def test_the_grant_lives_on_its_own_issue_not_the_hub():
    assert hosted.STANDING_ISSUE == 1924
    assert hosted.STANDING_ISSUE != 1823
