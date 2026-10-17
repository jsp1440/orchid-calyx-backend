"""The owner's discovery grant admits engine-filed work, by policy, fail-closed.

The per-issue standing grant lists issues by digest, so it cannot cover work the
engine discovers after the owner signs: #1968 was filed by the materializer,
claimed, and parked as ``governor:OWNER_ISSUE_AUTHORIZATION_REQUIRED``, and the
queue drained. The discovery grant is scoped by policy instead (lanes, sources,
exact paths, a daily cap, a reservation ceiling) and covers only issues the
workflow bot filed and nobody edited. It never authorizes merge to main,
deployment or scientific activation.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from scripts import oc_hosted_completion as hosted
from scripts import oc_paid_issue_admission as admission

REPO = "jsp1440/orchid-calyx-backend"
NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)
BOT = {"login": "github-actions[bot]", "type": "Bot"}
BODY = (
    "Continuous Brain pulse found an unresolved reasoning gap.\n\n"
    "## Routing\n\n"
    "- Product lane: Research Station\n"
    "- Discovery source: `brain-reasoning-gap`\n\n"
    "This task was filed by `scripts/oc_work_materialize.py` from a "
    "`scripts/oc_work_discovery.py` pass. No person selected it.\n\n"
    "OC-SWARM-READS: control-plane\n\n"
    "OC-DISCOVERY-FINGERPRINT: a55fd3efde161577"
)
PATHS = [
    "app/cognitive_integration/improvement_discovery.py",
    "tests/test_cognitive_integration_improvement_discovery.py",
]


def _issue(**overrides):
    issue = {
        "number": 1968,
        "state": "open",
        "title": "Reasoning gap: bee orchid pollination scope",
        "body": BODY,
        "user": dict(BOT),
        "labels": [
            {"name": "oc-queued"},
            {"name": "oc-discovered"},
            {"name": "oc-lane:research-station"},
        ],
    }
    issue.update(overrides)
    return issue


def _grant(**overrides):
    grant = {
        "repository": REPO,
        "target": hosted.BRANCH,
        "risk": "low",
        "expires_at": "2026-11-15T00:00:00Z",
        "max_issues_per_day": 3,
        "max_reserved_usd_per_issue": "0.50",
        "allowed_lanes": ["oc-lane:research-station"],
        "allowed_paths": list(PATHS),
        "allowed_sources": ["brain-reasoning-gap", "brain-mission-capability-gap"],
    }
    grant.update(overrides)
    return grant


def _record(grant=None, **overrides):
    record = {
        "id": 7100000001,
        "user": {"login": "jsp1440"},
        "author_association": "OWNER",
        "performed_via_github_app": None,
        "created_at": "2026-10-17T03:00:00Z",
        "updated_at": "2026-10-17T03:00:00Z",
        "body": "Discovery grant.\n\n"
        + hosted.tagged(hosted.DISCOVERY_TAG, grant if grant is not None else _grant()),
    }
    record.update(overrides)
    return record


def _history(**overrides):
    history = {"number": 1968, "last_edited_at": None, "renamed": 0}
    history.update(overrides)
    return history


def _authorize(issue=None, standing=None, history=None, comments=()):
    return hosted.authorization(
        issue or _issue(),
        list(comments),
        REPO,
        NOW,
        [_record()] if standing is None else standing,
        _history() if history is None else history,
    )


def _refused(detail, **kwargs):
    with pytest.raises(ValueError) as exc:
        _authorize(**kwargs)
    assert str(exc.value) == detail


# -- the grant ---------------------------------------------------------------


def test_an_owner_typed_grant_admits_an_unedited_discovered_issue():
    grant = _authorize()
    assert grant["discovery"] is True and grant["standing"] is True
    assert grant["comment_id"] == 7100000001
    assert grant["issue"] == 1968
    assert grant["target"] == "oc-autonomous-integration"
    assert grant["risk"] == "low"
    assert grant["checker_calls"] == 1
    assert grant["issue_material"] == hosted.issue_material(_issue())
    assert grant["allowed_paths"] == sorted(PATHS)
    assert grant["max_issues_per_day"] == 3
    assert grant["max_reserved_usd_per_issue"] == "0.50"


def test_the_grant_is_stable_across_rereads():
    """The checker compares the grant across phases; it must not drift."""
    assert _authorize() == _authorize()


def test_an_app_posted_grant_is_refused():
    app = _record(performed_via_github_app={"slug": "claude"})
    _refused("discovery_authorization_missing_or_ambiguous", standing=[app])


def test_an_edited_grant_is_refused():
    _refused(
        "authorization_edited",
        standing=[_record(updated_at="2026-10-17T04:00:00Z")],
    )


def test_an_expired_grant_is_refused():
    _refused(
        "authorization_expired",
        standing=[
            _record(
                _grant(expires_at="2026-10-17T06:00:00Z"),
            )
        ],
    )


def test_a_grant_longer_than_the_limit_is_refused():
    _refused(
        "discovery_authorization_invalid",
        standing=[_record(_grant(expires_at="2026-11-18T03:00:01Z"))],
    )


@pytest.mark.parametrize(
    "user",
    [
        {"login": "someone-else"},
        {"login": "github-actions[bot]"},
    ],
)
def test_a_non_owner_grant_is_refused(user):
    record = _record(user=user, author_association="NONE")
    _refused("discovery_authorization_missing_or_ambiguous", standing=[record])


def test_two_owner_grants_are_ambiguous_and_refused():
    record = _record()
    second = copy.deepcopy(record)
    second["id"] = 7100000002
    _refused("discovery_authorization_missing_or_ambiguous", standing=[record, second])


def test_a_stray_non_owner_copy_cannot_block_the_owner_grant():
    stray = _record(user={"login": "someone-else"}, author_association="NONE")
    assert _authorize(standing=[stray, _record()])["comment_id"] == 7100000001


@pytest.mark.parametrize(
    "overrides",
    [
        {"risk": "moderate"},
        {"target": "main"},
        {"repository": "fork/orchid-calyx-backend"},
        {"max_issues_per_day": 11},
        {"max_issues_per_day": 0},
        {"max_issues_per_day": True},
        {"max_issues_per_day": "3"},
        {"max_reserved_usd_per_issue": "2.01"},
        {"max_reserved_usd_per_issue": "0.00"},
        {"max_reserved_usd_per_issue": 0.5},
        {"max_reserved_usd_per_issue": "NaN"},
        {"allowed_lanes": []},
        {"allowed_lanes": ["research-station"]},
        {"allowed_lanes": ["oc-lane:a", "oc-lane:a"]},
        {"allowed_sources": []},
        {"allowed_sources": ["Brain Gap"]},
        {"allowed_paths": PATHS + PATHS[:1]},
        {"issues": {"1968": "0" * 64}},
    ],
)
def test_a_malformed_grant_is_refused(overrides):
    _refused("discovery_authorization_invalid", standing=[_record(_grant(**overrides))])


@pytest.mark.parametrize(
    "paths",
    [
        ["../etc/passwd"],
        ["AGENTS.md"],
        ["scripts/oc_paid_issue_admission.py"],
        ["scripts/oc_work_materialize.py"],
        [".github/workflows/orchid-completion-lane.yml"],
        [],
    ],
)
def test_protected_or_unsafe_grant_paths_are_refused(paths):
    _refused("unsafe_allowed_paths", standing=[_record(_grant(allowed_paths=paths))])


def test_a_missing_grant_is_refused():
    _refused("discovery_authorization_missing_or_ambiguous", standing=[])


# -- the issue ---------------------------------------------------------------


def _labels(*names):
    return [{"name": name} for name in names]


@pytest.mark.parametrize(
    ("issue", "detail"),
    [
        (_issue(state="closed"), "issue_not_open"),
        (_issue(pull_request={"url": "x"}), "issue_not_open"),
        (
            _issue(body=BODY.replace("This task was filed by", "Filed by")),
            "issue_not_engine_discovered",
        ),
        (
            _issue(body=BODY.replace("OC-DISCOVERY-FINGERPRINT: a55fd3efde161577", "")),
            "issue_not_engine_discovered",
        ),
        (
            _issue(body=BODY + "\nOC-DISCOVERY-FINGERPRINT: 0000000000000000"),
            "issue_not_engine_discovered",
        ),
        (
            _issue(
                body=BODY.replace("brain-reasoning-gap", "brain-source-contract-gap")
            ),
            "discovery_source_not_authorized",
        ),
        (
            _issue(body=BODY + "\n- Discovery source: `brain-reasoning-gap`"),
            "discovery_source_not_authorized",
        ),
        (
            _issue(labels=_labels("oc-queued", "oc-lane:research-station")),
            "issue_not_engine_discovered",
        ),
        (
            _issue(labels=_labels("oc-queued", "oc-discovered")),
            "discovery_lane_not_authorized",
        ),
        (
            _issue(labels=_labels("oc-discovered", "oc-lane:taxonomy")),
            "discovery_lane_not_authorized",
        ),
        (
            _issue(
                labels=_labels(
                    "oc-discovered", "oc-lane:research-station", "oc-lane:taxonomy"
                )
            ),
            "discovery_lane_not_authorized",
        ),
        (
            _issue(body=BODY + "\nOC-AUTO-REQUEUE: false"),
            "issue_owner_held",
        ),
        (
            _issue(body=BODY + "\nOC-SWARM-DISPOSITION: owner-gate"),
            "issue_owner_held",
        ),
        (
            _issue(body=BODY + "\nAllowed paths: `app/main.py`"),
            "issue_paths_outside_discovery_authorization",
        ),
    ],
)
def test_each_issue_qualification_rule_is_enforced(issue, detail):
    _refused(detail, issue=issue)


@pytest.mark.parametrize(
    "hold", ["oc-owner-gate", "blocked-on-owner", "oc-scientific-gate", "owner-gate"]
)
def test_an_owner_or_scientific_gated_discovered_issue_is_refused(hold):
    issue = _issue(
        labels=_labels("oc-queued", "oc-discovered", "oc-lane:research-station", hold)
    )
    _refused("issue_owner_held", issue=issue)


def test_a_forged_bot_looking_issue_opened_by_a_person_is_refused():
    """A person can copy every marker but cannot open an issue as the bot."""
    for user in ({"login": "jsp1440", "type": "User"}, {"login": "mallory"}):
        with pytest.raises(ValueError):
            _authorize(issue=_issue(user=user))
    # The bot login with a non-Bot account type is refused on the discovery path.
    _refused(
        "issue_not_engine_discovered",
        issue=_issue(user={"login": "github-actions[bot]", "type": "User"}),
    )


@pytest.mark.parametrize(
    "history",
    [
        _history(last_edited_at="2026-10-17T02:00:00Z"),
        _history(renamed=1),
        _history(number=1),
        {"number": 1968, "renamed": 0},
        {"number": 1968, "last_edited_at": None, "renamed": "0"},
        [],
    ],
)
def test_an_issue_edited_since_filing_is_refused(history):
    _refused("issue_edited_since_filed", history=history)


def test_missing_edit_history_is_refused():
    with pytest.raises(ValueError, match="issue_edited_since_filed"):
        hosted.authorization(_issue(), [], REPO, NOW, [_record()])


def test_declared_issue_paths_inside_the_grant_narrow_it():
    issue = _issue(body=BODY + f"\nAllowed paths: `{PATHS[1]}`")
    assert _authorize(issue=issue)["allowed_paths"] == [PATHS[1]]


def test_the_discovery_grant_cannot_admit_an_owner_opened_issue():
    """Owner-opened issues stay on the digest-listed standing grant."""
    with pytest.raises(ValueError, match="standing_authorization_missing_or_ambiguous"):
        _authorize(issue=_issue(user={"login": "jsp1440", "type": "User"}))


def test_a_per_issue_record_still_decides_alone():
    with pytest.raises(ValueError, match="hosted_authorization_missing_or_ambiguous"):
        _authorize(
            comments=[{"body": hosted.AUTH_TAG}, {"body": hosted.AUTH_TAG}],
        )


# -- paid admission: reservation ceiling and daily cap -----------------------


class Ledger:
    def __init__(self, bodies=(), fail_append=False):
        self.rows = [{"body": body} for body in bodies]
        self.appended = []
        self.since_calls = []
        self.fail_append = fail_append

    def since(self, moment):
        self.since_calls.append(moment)
        return list(self.rows)

    def append(self, body):
        if self.fail_append:
            raise RuntimeError("receipt_unconfirmed")
        self.appended.append(body)
        self.rows.append({"body": body})
        return 1


def _receipt(day="2026-10-17", issue=1900):
    return (
        f"[OC-DISCOVERY-ADMISSION] grant=7100000001 issue={issue} run_id=1 date={day}"
    )


def _admit(issue=None, ledger=None, reserved="0.50", standing=None):
    issue = issue or _issue()
    return admission.admit(
        REPO,
        issue["number"],
        fetch=lambda *_: (
            issue,
            [],
            lambda: standing if standing is not None else [_record()],
            lambda: _history(number=issue["number"]),
        ),
        now=NOW,
        reserved_usd=reserved,
        ledger=ledger if ledger is not None else Ledger(),
        run_id="38990149027",
    )


def test_a_discovery_admission_records_a_durable_receipt():
    ledger = Ledger()
    decision = _admit(ledger=ledger)
    assert decision["authorized"] is True
    assert decision["discovery"] is True and decision["standing"] is True
    assert ledger.since_calls == ["2026-10-17T00:00:00Z"]
    assert ledger.appended == [
        (
            "[OC-DISCOVERY-ADMISSION] grant=7100000001 issue=1968 "
            "run_id=38990149027 date=2026-10-17"
        )
    ]


def test_the_daily_cap_is_counted_from_receipts_and_enforced():
    ledger = Ledger(
        [
            _receipt(issue=1),
            _receipt(issue=2),
            _receipt(day="2026-10-16", issue=3),
            (
                "[OC-GOVERNOR-COST] run_id=1 issue=4 provider=anthropic "
                "reserved_usd=0.50 actual_usd=unknown date=2026-10-17 month=2026-10"
            ),
        ]
    )
    assert _admit(ledger=ledger)["authorized"] is True  # third of three today
    decision = _admit(ledger=ledger)
    assert decision["authorized"] is False
    assert decision["reason"] == "OWNER_ISSUE_AUTHORIZATION_REQUIRED"
    assert decision["detail"] == "discovery_daily_cap_reached"
    assert len(ledger.appended) == 1


def test_receipts_in_one_comment_each_count():
    ledger = Ledger(
        ["\n".join([_receipt(issue=1), _receipt(issue=2), _receipt(issue=3)])]
    )
    assert _admit(ledger=ledger)["detail"] == "discovery_daily_cap_reached"


@pytest.mark.parametrize("reserved", ["0.51", "2.00", "", "abc", "NaN", "-1", "0"])
def test_a_reservation_above_the_grant_ceiling_is_refused(reserved):
    ledger = Ledger()
    decision = _admit(ledger=ledger, reserved=reserved)
    assert decision["authorized"] is False
    assert decision["detail"] in {
        "discovery_reservation_exceeds_grant",
        "discovery_reservation_unknown",
    }
    assert ledger.appended == []


def test_an_unconfirmed_receipt_refuses_admission():
    decision = _admit(ledger=Ledger(fail_append=True))
    assert decision["authorized"] is False
    assert decision["detail"] == "receipt_unconfirmed"


def test_a_ledger_read_failure_refuses_admission():
    class Broken(Ledger):
        def since(self, moment):
            raise OSError("api unavailable")

    assert _admit(ledger=Broken())["authorized"] is False


def test_a_refused_issue_writes_no_receipt():
    ledger = Ledger()
    issue = _issue(
        labels=_labels("oc-discovered", "oc-lane:research-station", "oc-owner-gate")
    )
    decision = _admit(issue=issue, ledger=ledger)
    assert decision["authorized"] is False
    assert decision["detail"] == "issue_owner_held"
    assert ledger.appended == []


def test_a_standing_grant_admission_writes_no_discovery_receipt():
    ledger = Ledger()
    owner_issue = {
        "number": 1914,
        "state": "open",
        "title": "Owner task",
        "body": "Allowed paths:\n- `app/archive/parser.py`\n- `tests/test_archive.py`\n",
        "user": {"login": "jsp1440"},
        "labels": [{"name": "oc-queued"}],
    }
    standing = {
        "id": 7000000001,
        "user": {"login": "jsp1440"},
        "author_association": "OWNER",
        "performed_via_github_app": None,
        "created_at": "2026-10-16T03:00:00Z",
        "updated_at": "2026-10-16T03:00:00Z",
        "body": hosted.tagged(
            hosted.STANDING_TAG,
            {
                "repository": REPO,
                "target": hosted.BRANCH,
                "risk": "low",
                "expires_at": "2026-11-15T00:00:00Z",
                "issues": {"1914": hosted.issue_material(owner_issue)},
            },
        ),
    }
    decision = _admit(
        issue=owner_issue, ledger=ledger, standing=[standing], reserved=""
    )
    assert decision["authorized"] is True
    assert decision["discovery"] is False
    assert ledger.appended == []


def test_the_documented_grant_parses_and_admits():
    """The JSON the owner is told to post must itself be a valid grant."""
    import json
    import re
    from pathlib import Path

    doc = Path("docs/brain/OC-HOSTED-FACTORY-CONTINUATION.md").read_text(
        encoding="utf-8"
    )
    (block,) = re.findall(
        r"<!-- OC-HOSTED-DISCOVERY-AUTHORIZATION-V1\n(.*?)\n-->", doc, re.DOTALL
    )
    grant = json.loads(block)
    assert set(grant) == hosted.DISCOVERY_FIELDS
    record = _record(grant)
    issue = _issue(
        body=BODY,
        labels=_labels("oc-queued", "oc-discovered", grant["allowed_lanes"][0]),
    )
    issue["body"] = BODY.replace("brain-reasoning-gap", grant["allowed_sources"][0])
    hosted._discovery_grant(record, REPO)
    assert (
        hosted.discovery_authorization(
            issue, [record], REPO, datetime(2026, 10, 18, tzinfo=UTC), _history()
        )["discovery"]
        is True
    )
