"""The owner's standing grant admits a listed batch of owner-opened issues.

Per-issue records made the owner sign every task; a standing grant replaces
that for a batch without letting the maker authorize itself. Only a comment the
owner typed directly counts, never one posted through an app, and it lists each
issue with the digest of the text the owner saw, so an issue opened or edited
afterwards (an agent with the owner's token can do both) is not covered.
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


def _grant(issues=None, **overrides):
    grant = {
        "repository": REPO,
        "target": hosted.BRANCH,
        "risk": "low",
        "expires_at": "2026-11-15T00:00:00Z",
        "issues": issues
        if issues is not None
        else {"1914": hosted.issue_material(_issue())},
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


def test_an_owner_typed_grant_admits_a_listed_unchanged_issue():
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


def test_the_standing_comments_are_read_only_without_a_per_issue_record():
    calls = []

    def read():
        calls.append(1)
        return [_record()]

    assert _authorize(_issue(), read)["standing"] is True
    assert calls == [1]
    issue = _issue()
    per_issue = _record(
        body=hosted.tagged(
            hosted.AUTH_TAG,
            {
                "repository": REPO,
                "issue": 1914,
                "issue_material": hosted.issue_material(issue),
                "target": hosted.BRANCH,
                "checker_calls": 1,
                "risk": "low",
                "allowed_paths": ["app/archive/parser.py"],
                "expires_at": "2026-10-20T00:00:00Z",
            },
        )
    )
    assert _authorize(issue, read, comments=[per_issue])["comment_id"] == 7000000001
    assert calls == [1]


def test_an_issue_opened_after_the_grant_is_not_covered():
    """Review B1: an agent opens a new issue under the owner's account."""
    later = _issue(number=1940, body="Allowed paths: `app/archive/manager.py`\n")
    with pytest.raises(ValueError, match="issue_outside_standing_authorization"):
        _authorize(later, [_record()])


def test_an_issue_edited_after_the_grant_is_not_covered():
    edited = _issue(body=BODY + "\nAlso rewrite the governor.\n")
    with pytest.raises(ValueError, match="issue_material_changed"):
        _authorize(edited, [_record()])
    retitled = _issue(title="Something else entirely")
    with pytest.raises(ValueError, match="issue_material_changed"):
        _authorize(retitled, [_record()])


def test_a_grant_posted_through_an_app_never_counts():
    """The maker posts with the owner's token through the Claude app."""
    record = _record(performed_via_github_app={"slug": "claude"})
    with pytest.raises(ValueError, match="standing_authorization_missing"):
        _authorize(_issue(), [record])


def test_a_stray_tagged_comment_cannot_block_the_owner_grant():
    stray = _record(
        id=7000000009, user={"login": "drive-by"}, author_association="NONE"
    )
    agent = _record(id=7000000010, performed_via_github_app={"slug": "claude"})
    assert _authorize(_issue(), [stray, _record(), agent])["comment_id"] == 7000000001


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


MATERIAL = hosted.issue_material(_issue())


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (_record(updated_at="2026-10-16T04:00:00Z"), "authorization_edited"),
        (_record(_grant(risk="moderate")), "standing_authorization_invalid"),
        (_record(_grant(target="main")), "standing_authorization_invalid"),
        (_record(_grant(repository="other/repo")), "standing_authorization_invalid"),
        (_record(_grant(checker_calls=5)), "standing_authorization_invalid"),
        (_record(_grant(issues={})), "standing_authorization_invalid"),
        (_record(_grant(issues=[1914])), "standing_authorization_invalid"),
        (_record(_grant(issues={"1914": "abc"})), "standing_authorization_invalid"),
        (_record(_grant(issues={"01914": MATERIAL})), "standing_authorization_invalid"),
        (_record(_grant(issues={"x": MATERIAL})), "standing_authorization_invalid"),
        (
            _record(_grant(issues={str(n): MATERIAL for n in range(1, 52)})),
            "standing_authorization_invalid",
        ),
        (
            _record(_grant(expires_at="2026-11-17T03:00:01Z")),
            "standing_authorization_invalid",
        ),
        (_record(_grant(expires_at="2026-10-16T00:00:00Z")), "authorization_expired"),
        (_record(_grant(expires_at="2026-11-15T00:00:00")), "timestamp_invalid"),
        (_record(_grant(expires_at=20261115)), "timestamp_invalid"),
        (_record(_grant(expires_at=None)), "timestamp_invalid"),
        (
            _record(_grant(issues={"1915": MATERIAL})),
            "issue_outside_standing_authorization",
        ),
    ],
)
def test_every_invalid_or_stale_grant_is_refused(record, reason):
    with pytest.raises(ValueError, match=reason):
        _authorize(_issue(), [record])


@pytest.mark.parametrize(
    "record",
    [
        _record(user={"login": "someone-else"}),
        _record(author_association="COLLABORATOR"),
        _record(user=None),
    ],
)
def test_only_owner_rows_can_carry_a_grant(record):
    with pytest.raises(ValueError, match="standing_authorization_missing"):
        _authorize(_issue(), [record])


def test_two_owner_grants_are_ambiguous():
    with pytest.raises(ValueError, match="standing_authorization_missing_or_ambiguous"):
        _authorize(_issue(), [])
    with pytest.raises(ValueError, match="standing_authorization_missing_or_ambiguous"):
        _authorize(_issue(), [_record(), _record(id=7000000002)])


@pytest.mark.parametrize(
    ("issue", "reason"),
    [
        (_issue(user={"login": "drive-by"}), "issue_not_owner_opened"),
        (_issue(state="closed"), "issue_not_open"),
        (_issue(pull_request={"url": "x"}), "issue_not_open"),
    ],
)
def test_the_issue_itself_must_be_an_open_owner_issue(issue, reason):
    grant = _grant(issues={"1914": hosted.issue_material(issue)})
    with pytest.raises(ValueError, match=reason):
        _authorize(issue, [_record(grant)])


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
    issue = _issue(body=body)
    grant = _grant(issues={"1914": hosted.issue_material(issue)})
    with pytest.raises(ValueError, match="unsafe_allowed_paths"):
        _authorize(issue, [_record(grant)])


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
        REPO,
        issue["number"],
        fetch=lambda *_: (issue, [], lambda: [_record()]),
        now=NOW,
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
    assert decision["detail"] == "standing_authorization_missing_or_ambiguous"


def test_the_grant_lives_on_its_own_issue_not_the_hub():
    assert hosted.STANDING_ISSUE == 1924
    assert hosted.STANDING_ISSUE != 1823
