"""Filing discovered work once, and never again for the same condition.

A discoverer that runs every five minutes and files an issue each time is worse
than no discoverer at all, so nearly every test here is about the second pass.
"""

from __future__ import annotations

import copy
import json
import subprocess

import pytest

from scripts import oc_work_materialize as materialize

REPO = "jsp1440/orchid-calyx-backend"


def candidate(fingerprint: str = "a" * 16, *, rank: int = 1, lane: str | None = "calyx") -> dict:
    return {
        "schema": "oc.work-candidate.v1",
        "source": "dependency-gap",
        "title": "Declare pytest-asyncio so 8 test file(s) execute instead of reporting unrun",
        "summary": "Eight files use a marker no requirements file declares.",
        "lane": lane,
        "lane_name": "Calyx" if lane else None,
        "rank": rank,
        "analysis_only": False,
        "fingerprint": fingerprint,
        "semantic_key": f"dependency-gap:{fingerprint}",
        "proposed_remedy": "Add a pinned requirement and re-run the affected files.",
        "capabilities": ["test-execution"],
        "labels": ["oc-queued", "oc-p1", "oc-discovered", "oc-lane:calyx"],
        "evidence": [
            {"kind": "marker-without-distribution", "where": "tests/test_calyx_brain_x.py",
             "detail": "uses a pytest marker supplied by 'pytest-asyncio'"}
        ],
    }


def report(*candidates: dict) -> dict:
    return {
        "schema": "oc.work-discovery.v1",
        "candidate_count": len(candidates),
        "candidates": list(candidates),
        "suppressed_by_dependency_gap": [],
        "safety": {},
    }


class FakeGitHub:
    """Records writes; serves the issues it has been told exist."""

    def __init__(self, bodies: list[str] | None = None) -> None:
        self.bodies = list(bodies or [])
        self.calls: list[list[str]] = []
        self.next_number = 2000
        self.fail_create = False

    def __call__(self, args, payload=None):
        self.calls.append(copy.deepcopy(args))
        if args[:2] == ["label", "create"]:
            return None
        if args[:2] == ["issue", "list"]:
            return [{"number": index, "body": body} for index, body in enumerate(self.bodies, 1)]
        if args[:2] == ["issue", "create"]:
            if self.fail_create:
                raise subprocess.SubprocessError("redacted")
            body = args[args.index("--body") + 1]
            self.bodies.append(body)
            self.next_number += 1
            return f"https://github.com/{REPO}/issues/{self.next_number}"
        raise AssertionError(f"unexpected call {args}")


class TestIdentityIsTheCondition:
    def test_a_fresh_candidate_is_filed(self) -> None:
        transport = FakeGitHub()
        result = materialize.apply_plan(
            materialize.plan(report(candidate()), set()), REPO, dry_run=False, call=transport
        )
        assert result["created_count"] == 1
        assert result["results"][0]["issue_number"] == 2001

    def test_the_second_pass_over_an_unchanged_repository_files_nothing(self) -> None:
        transport = FakeGitHub()
        first = materialize.plan(report(candidate()), set())
        materialize.apply_plan(first, REPO, dry_run=False, call=transport)
        known = materialize.existing_fingerprints(REPO, call=transport)
        second = materialize.plan(report(candidate()), known)
        assert second["action_count"] == 0
        assert second["skipped"][0]["reason"] == "already_filed"

    def test_a_closed_issue_still_counts_as_filed(self) -> None:
        """Otherwise every defect anyone resolved returns on the next pulse."""
        closed = materialize.issue_body(candidate())
        transport = FakeGitHub(bodies=[closed])
        known = materialize.existing_fingerprints(REPO, call=transport)
        assert materialize.plan(report(candidate()), known)["action_count"] == 0

    def test_a_race_between_two_waves_files_once(self) -> None:
        transport = FakeGitHub()
        planned = materialize.plan(report(candidate()), set())
        materialize.apply_plan(planned, REPO, dry_run=False, call=transport)
        # The loser planned against a stale snapshot and re-checks before writing.
        again = materialize.apply_plan(planned, REPO, dry_run=False, call=transport)
        assert again["results"][0]["outcome"] == "already_filed"
        assert sum(call[:2] == ["issue", "create"] for call in transport.calls) == 1

    def test_a_malformed_fingerprint_is_never_filed(self) -> None:
        planned = materialize.plan(report(candidate(fingerprint="nope")), set())
        assert planned["action_count"] == 0
        assert planned["skipped"][0]["reason"] == "unusable_fingerprint"


class TestBounded:
    def test_a_pass_files_at_most_max_new(self) -> None:
        candidates = [candidate(fingerprint=f"{index:016x}") for index in range(10)]
        planned = materialize.plan(report(*candidates), set(), max_new=3)
        assert planned["action_count"] == 3
        assert sum(row["reason"] == "bounded_by_max_new" for row in planned["skipped"]) == 7

    def test_the_highest_ranked_candidates_are_the_ones_filed(self) -> None:
        low = candidate(fingerprint="b" * 16, rank=5, lane=None)
        high = candidate(fingerprint="c" * 16, rank=1)
        planned = materialize.plan(report(high, low), set(), max_new=1)
        assert planned["actions"][0]["fingerprint"] == "c" * 16

    def test_dry_run_is_the_default_and_writes_nothing(self) -> None:
        transport = FakeGitHub()
        result = materialize.apply_plan(
            materialize.plan(report(candidate()), set()), REPO, call=transport
        )
        assert result["dry_run"] is True
        assert result["created_count"] == 0
        assert transport.calls == []


class TestTheIssueItFiles:
    def test_the_body_carries_the_fingerprint_and_the_swarm_markers(self) -> None:
        body = materialize.issue_body(candidate())
        assert materialize.FINGERPRINT.search(body)
        assert "OC-SWARM-CAPABILITY: test-execution" in body
        assert "OC-SWARM-READS: control-plane" in body

    def test_the_body_carries_every_piece_of_evidence(self) -> None:
        body = materialize.issue_body(candidate())
        assert "tests/test_calyx_brain_x.py" in body

    def test_an_unbound_candidate_says_so_rather_than_naming_a_lane(self) -> None:
        body = materialize.issue_body(candidate(lane=None))
        assert "UNBOUND" in body
        assert "Product lane: Calyx" not in body

    def test_the_body_says_no_person_selected_it(self) -> None:
        assert "No person selected it" in materialize.issue_body(candidate())


class TestFailClosed:
    def test_an_unrecognised_report_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unrecognised discovery report"):
            materialize.plan({"schema": "something.else"}, set())

    def test_an_invalid_repository_is_refused(self) -> None:
        with pytest.raises(ValueError, match="invalid repository"):
            materialize.apply_plan(materialize.plan(report(), set()), "not a repo", dry_run=False)

    def test_one_failed_creation_does_not_stop_the_rest(self) -> None:
        transport = FakeGitHub()
        transport.fail_create = True
        result = materialize.apply_plan(
            materialize.plan(report(candidate()), set()), REPO, dry_run=False, call=transport
        )
        assert result["created_count"] == 0
        assert result["errors"][0]["reason"] == "materialization_unconfirmed"

    def test_a_creation_that_returns_no_url_is_not_reported_as_created(self) -> None:
        class NoUrl(FakeGitHub):
            def __call__(self, args, payload=None):
                if args[:2] == ["issue", "create"]:
                    self.calls.append(args)
                    return "something that is not a url"
                return super().__call__(args, payload)

        transport = NoUrl()
        result = materialize.apply_plan(
            materialize.plan(report(candidate()), set()), REPO, dry_run=False, call=transport
        )
        assert result["created_count"] == 0
        assert result["errors"]

    def test_the_round_trip_body_is_readable_by_the_fingerprint_reader(self) -> None:
        transport = FakeGitHub()
        materialize.apply_plan(
            materialize.plan(report(candidate()), set()), REPO, dry_run=False, call=transport
        )
        assert materialize.existing_fingerprints(REPO, call=transport) == {"a" * 16}


def test_the_plan_is_json_serialisable_for_the_workflow() -> None:
    json.dumps(materialize.plan(report(candidate()), set()))


class TestLabelsExistBeforeTheWrite:
    def test_every_label_is_created_before_the_issue(self) -> None:
        """A label the repository lacks fails `gh issue create` outright.

        The first live pass filed nothing for this reason and reported success.
        """
        transport = FakeGitHub()
        materialize.apply_plan(
            materialize.plan(report(candidate()), set()), REPO, dry_run=False, call=transport
        )
        kinds = [call[:2] for call in transport.calls]
        assert ["label", "create"] in kinds
        assert kinds.index(["label", "create"]) < kinds.index(["issue", "create"])

    def test_each_of_the_four_labels_is_ensured(self) -> None:
        transport = FakeGitHub()
        materialize.apply_plan(
            materialize.plan(report(candidate()), set()), REPO, dry_run=False, call=transport
        )
        created = {call[2] for call in transport.calls if call[:2] == ["label", "create"]}
        assert created == {"oc-queued", "oc-p1", "oc-discovered", "oc-lane:calyx"}

    def test_creation_is_idempotent(self) -> None:
        transport = FakeGitHub()
        materialize.apply_plan(
            materialize.plan(report(candidate()), set()), REPO, dry_run=False, call=transport
        )
        assert all(
            "--force" in call for call in transport.calls if call[:2] == ["label", "create"]
        )

    def test_a_label_outside_this_modules_vocabulary_is_refused(self) -> None:
        """Filing an issue is not authority to invent repository vocabulary."""
        with pytest.raises(ValueError, match="outside this module's vocabulary"):
            materialize.ensure_labels(REPO, ["something-someone-typoed"], call=FakeGitHub())

    def test_any_lane_label_is_allowed_because_the_table_owns_that_shape(self) -> None:
        transport = FakeGitHub()
        assert materialize.ensure_labels(REPO, ["oc-lane:vision-lab"], call=transport) == [
            "oc-lane:vision-lab"
        ]

    def test_a_dry_run_creates_no_labels_either(self) -> None:
        transport = FakeGitHub()
        materialize.apply_plan(
            materialize.plan(report(candidate()), set()), REPO, call=transport
        )
        assert transport.calls == []


class TestDedupeSurvivesASlowSearchIndex:
    """The filing loop this module would otherwise run every five minutes.

    `gh issue list --search` is served from GitHub's asynchronously maintained
    search index; `--label` is served from the ordinary REST issue collection,
    which is read-after-write consistent. The first implementation used the
    search alone, so while an issue was unindexed every controller pass re-filed
    its condition -- including the re-check immediately before the write, which
    asked the same lagging index and therefore protected nothing. Four passes
    produced four identical issues.
    """

    class LaggingSearch(FakeGitHub):
        """Label listing is current; the search index never catches up."""

        def __call__(self, args, payload=None):
            if args[:2] == ["issue", "list"] and "--search" in args and "--label" not in args:
                self.calls.append(copy.deepcopy(args))
                return []
            return super().__call__(args, payload)

    def run_waves(self, transport, waves: int = 6) -> None:
        for _ in range(waves):
            known = materialize.existing_fingerprints(REPO, call=transport)
            materialize.apply_plan(
                materialize.plan(report(candidate()), known), REPO, dry_run=False, call=transport
            )

    def test_one_issue_across_many_waves_though_search_never_indexes_it(self) -> None:
        transport = self.LaggingSearch()
        self.run_waves(transport)
        creations = [call for call in transport.calls if call[:2] == ["issue", "create"]]
        assert len(creations) == 1

    def test_the_lookup_asks_the_consistent_collection_not_only_the_index(self) -> None:
        transport = FakeGitHub()
        materialize.existing_fingerprints(REPO, call=transport)
        listings = [call for call in transport.calls if call[:2] == ["issue", "list"]]
        assert any("--label" in call for call in listings), "no read-after-write consistent lookup"
        assert any("--search" in call for call in listings), "search fallback dropped"

    def test_search_still_catches_an_issue_whose_label_was_removed(self) -> None:
        """The label lookup cannot see it; that is why the search one stays."""

        class LabelStripped(FakeGitHub):
            def __call__(self, args, payload=None):
                if args[:2] == ["issue", "list"] and "--label" in args:
                    self.calls.append(copy.deepcopy(args))
                    return []
                return super().__call__(args, payload)

        transport = LabelStripped(bodies=[materialize.issue_body(candidate())])
        assert materialize.existing_fingerprints(REPO, call=transport) == {"a" * 16}

    def test_both_lookups_read_closed_issues_too(self) -> None:
        transport = FakeGitHub()
        materialize.existing_fingerprints(REPO, call=transport)
        listings = [call for call in transport.calls if call[:2] == ["issue", "list"]]
        assert all("--state" in call and call[call.index("--state") + 1] == "all" for call in listings)

    def test_an_unavailable_lookup_fails_closed_rather_than_narrowing(self) -> None:
        """Narrowing the already-filed set is the direction that files duplicates."""

        class Broken(FakeGitHub):
            def __call__(self, args, payload=None):
                if args[:2] == ["issue", "list"]:
                    raise subprocess.SubprocessError("redacted")
                return super().__call__(args, payload)

        with pytest.raises(subprocess.SubprocessError):
            materialize.existing_fingerprints(REPO, call=Broken())

    def test_the_window_is_wide_enough_to_be_a_ceiling_not_a_page(self) -> None:
        transport = FakeGitHub()
        materialize.existing_fingerprints(REPO, call=transport)
        for call in (c for c in transport.calls if c[:2] == ["issue", "list"]):
            assert int(call[call.index("--limit") + 1]) >= 1000
