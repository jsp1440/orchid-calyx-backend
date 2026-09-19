"""Releasing blocked work is a claim about the world, and must be checked.

``oc-blocked`` holds an issue outside the execution portfolio, and the only code
that removes it runs after a lane executes the issue — which a blocked issue is
never selected for. These tests pin the two halves of the fix: a blocker that
demonstrably cleared releases, and everything else is held with its reason kept.

The dangerous failure here is the cheerful one. A reconciler that releases on
age, or on an unreadable blocker, re-admits genuinely stopped work and looks
productive doing it.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before exec because `@dataclass` resolves annotations through
    # `sys.modules[cls.__module__]`, which is absent for a path-loaded module.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


reconcile_module = _load("oc_blocked_reconcile")
Disposition = reconcile_module.Disposition
WorldState = reconcile_module.WorldState
reconcile = reconcile_module.reconcile
reconcile_issue = reconcile_module.reconcile_issue
to_report = reconcile_module.to_report


def issue(number: int, *, body: str = "", labels=("oc-blocked",), comments=()) -> dict:
    return {
        "number": number,
        "state": "OPEN",
        "body": body,
        "labels": list(labels),
        "comments": [{"body": c} for c in comments],
    }


class TestAClearedBlockerReleases:
    def test_a_closed_issue_releases_what_waited_on_it(self) -> None:
        result = reconcile_issue(
            issue(10, comments=["BLOCKED on the parser.\nOC-BLOCKED-ON: #9"]),
            WorldState(closed_issues={9}),
        )
        assert result.disposition is Disposition.RELEASE
        assert "#9" in result.reason

    def test_a_merged_pull_request_releases_what_waited_on_it(self) -> None:
        # #1502's actual shape: blocked by a defect, repaired in a PR that merged.
        result = reconcile_issue(
            issue(1502, comments=["OC-BLOCKED-ON: pr#1504"]),
            WorldState(merged_prs={1504}),
        )
        assert result.disposition is Disposition.RELEASE
        assert result.blocker == "pr#1504"

    def test_the_record_may_live_in_the_body_or_a_comment(self) -> None:
        in_body = reconcile_issue(issue(11, body="OC-BLOCKED-ON: #9"), WorldState(closed_issues={9}))
        in_comment = reconcile_issue(issue(12, comments=["OC-BLOCKED-ON: #9"]), WorldState(closed_issues={9}))
        assert in_body.disposition is in_comment.disposition is Disposition.RELEASE


class TestEverythingElseIsHeld:
    def test_an_open_blocker_holds(self) -> None:
        result = reconcile_issue(
            issue(10, comments=["OC-BLOCKED-ON: #9"]), WorldState(open_issues={9})
        )
        assert result.disposition is Disposition.HOLD

    def test_an_unmerged_pull_request_holds(self) -> None:
        result = reconcile_issue(
            issue(10, comments=["OC-BLOCKED-ON: pr#9"]), WorldState(unmerged_prs={9})
        )
        assert result.disposition is Disposition.HOLD

    def test_an_unknown_blocker_state_holds_rather_than_releasing(self) -> None:
        """Absence of evidence that it still stands is not evidence it lifted."""
        result = reconcile_issue(issue(10, comments=["OC-BLOCKED-ON: #9"]), WorldState())
        assert result.disposition is Disposition.HOLD
        assert "not the same as cleared" in result.reason

    def test_no_record_at_all_is_unverifiable_and_never_released(self) -> None:
        # The common case today: AGENTS.md asks for a prose BLOCKED comment, so
        # the existing blocked issues have no checkable record. Reporting them
        # is the honest move; guessing would re-admit stopped work.
        result = reconcile_issue(
            issue(10, comments=["BLOCKED: the vendor API is down and nobody knows when."]),
            WorldState(),
        )
        assert result.disposition is Disposition.UNVERIFIABLE
        assert "cannot be checked" in result.reason

    def test_a_listing_shaped_issue_holds_instead_of_crashing(self) -> None:
        """GitHub's issue *listing* gives ``comments`` as a count, not a list.

        Found by running this against the repository's real blocked backlog,
        which is the shape a caller most easily reaches for. A crash here would
        take out the whole reconciliation pass; the right answer is that no
        record was found, which holds.
        """
        listing_shaped = {
            "number": 1502,
            "state": "OPEN",
            "body": "Architecture: ...",
            "labels": ["oc-blocked"],
            "comments": 7,
        }
        result = reconcile_issue(listing_shaped, WorldState())
        assert result.disposition is Disposition.UNVERIFIABLE
        assert not result.releases

    def test_a_blocker_form_it_cannot_parse_is_unverifiable(self) -> None:
        result = reconcile_issue(
            issue(10, comments=["OC-BLOCKED-ON: the-weather"]), WorldState()
        )
        assert result.disposition is Disposition.UNVERIFIABLE
        assert result.blocker == "the-weather"


class TestWhatItMayNeverRelease:
    @pytest.mark.parametrize(
        "form", ["owner-decision", "credential", "spend", "budget-increase", "deployment"]
    )
    def test_a_persons_decision_is_never_cleared_by_this_module(self, form: str) -> None:
        result = reconcile_issue(
            issue(10, comments=[f"OC-BLOCKED-ON: {form}"]),
            # Even with a world state that would clear anything checkable.
            WorldState(closed_issues=set(range(100)), merged_prs=set(range(100))),
        )
        assert result.disposition is Disposition.OWNER_GATE
        assert not result.releases

    def test_an_owner_gate_label_outranks_a_cleared_blocker(self) -> None:
        result = reconcile_issue(
            issue(10, labels=("oc-blocked", "oc-owner-gate"), comments=["OC-BLOCKED-ON: #9"]),
            WorldState(closed_issues={9}),
        )
        assert result.disposition is Disposition.OWNER_GATE

    def test_a_deliberate_park_outranks_everything(self) -> None:
        # The Stage C canaries say this explicitly; it is not an oversight to fix.
        result = reconcile_issue(
            issue(1424, body="OC-AUTO-REQUEUE: false\nOC-BLOCKED-ON: #9"),
            WorldState(closed_issues={9}),
        )
        assert result.disposition is Disposition.PARKED
        assert not result.releases

    def test_nothing_is_released_on_age(self) -> None:
        """There is no clock here, and the absence is the point.

        A reconciler that releases stale blocks looks productive while
        re-admitting work that is genuinely stopped. Nothing in this module
        reads a timestamp.
        """
        import inspect

        source = inspect.getsource(reconcile_module)
        for temporal in ("datetime", "time.time", "updated_at", "created_at", "timedelta"):
            assert temporal not in source, f"{temporal!r} would let age decide a release"


class TestTheReport:
    def test_it_names_the_work_nothing_will_ever_look_at_again(self) -> None:
        results = reconcile(
            [
                issue(1, comments=["OC-BLOCKED-ON: pr#100"]),
                issue(2, comments=["BLOCKED: prose only, no record."]),
                issue(3, comments=["OC-BLOCKED-ON: credential"]),
                issue(4, body="OC-AUTO-REQUEUE: false"),
            ],
            WorldState(merged_prs={100}),
        )
        report = to_report(results)
        assert report["release_numbers"] == [1]
        assert report["unverifiable_numbers"] == [2]
        assert report["counts"]["owner-gate"] == 1
        assert report["counts"]["parked"] == 1

    def test_it_ignores_issues_that_are_not_blocked(self) -> None:
        results = reconcile(
            [
                issue(1, labels=("oc-queued",), comments=["OC-BLOCKED-ON: #9"]),
                issue(2, comments=["OC-BLOCKED-ON: #9"]),
            ],
            WorldState(closed_issues={9}),
        )
        assert [r.issue_number for r in results] == [2]

    def test_it_ignores_closed_issues(self) -> None:
        closed = issue(1, comments=["OC-BLOCKED-ON: #9"])
        closed["state"] = "CLOSED"
        assert reconcile([closed], WorldState(closed_issues={9})) == []

    def test_every_record_states_its_own_authority(self) -> None:
        """A caller must not infer permission to relabel from anything but this."""
        results = reconcile(
            [issue(1, comments=["OC-BLOCKED-ON: pr#100"]), issue(2, comments=["no record"])],
            WorldState(merged_prs={100}),
        )
        records = {r["issue_number"]: r for r in to_report(results)["results"]}
        assert records[1]["release_authorized"] is True
        assert records[2]["release_authorized"] is False
        assert all(r["reason"] for r in records.values())
