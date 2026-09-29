"""Filing discovered work once, and never again for the same condition.

A discoverer that runs every five minutes and files an issue each time is worse
than no discoverer at all, so nearly every test here is about the second pass --
or the thousand-and-first.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from scripts import oc_work_materialize as materialize

REPO = "jsp1440/orchid-calyx-backend"
FP = "a" * 16


def candidate(fingerprint: str = FP, *, rank: int = 1, lane: str | None = "calyx") -> dict:
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


def report(*candidates: dict, sources: tuple[str, ...] = ("dependency-gap", "undeclared-import", "binding-gap")) -> dict:
    return {
        "schema": "oc.work-discovery.v1",
        "sources_evaluated": list(sources),
        "candidate_count": len(candidates),
        "candidates": list(candidates),
        "suppressed_by_dependency_gap": [],
        "safety": {},
    }


def filed(fingerprint: str = FP) -> str:
    return materialize.issue_body(candidate(fingerprint))


class FakeGitHub:
    """A repository's issues, served the way `gh` serves them.

    The GraphQL connection is the primary store: it pages, it is current, and
    its ``totalCount`` is the truth. The search index is separate and can be
    told to lag -- for every issue, or for issues filed after construction.
    """

    def __init__(self, issues: list[dict] | None = None, *, search_lags: bool = False) -> None:
        self.issues: list[dict] = []
        for issue in issues or []:
            if "stateReason" in issue:  # already in stored form: another fake's issues
                self.issues.append({**issue, "labels": set(issue["labels"])})
            else:
                self.add(**issue)
        self.calls: list[list[str]] = []
        self.search_lags = search_lags
        self.indexed = {issue["number"] for issue in self.issues}
        self.fail_create = False

    def add(self, body: str, *, number: int | None = None, state: str = "OPEN",
            reason: str | None = None, labels: tuple[str, ...] = ("oc-discovered", "oc-queued")) -> dict:
        issue = {
            "number": number if number is not None else (max([i["number"] for i in self.issues], default=0) + 1),
            "state": state,
            "stateReason": reason,
            "body": body,
            "labels": set(labels),
        }
        self.issues.append(issue)
        return issue

    def get(self, number: int) -> dict:
        return next(issue for issue in self.issues if issue["number"] == number)

    def of(self, fingerprint: str) -> list[dict]:
        return [i for i in self.issues if f"{materialize.FINGERPRINT_MARKER}: {fingerprint}" in i["body"]]

    def writes(self, *kinds: str) -> list[list[str]]:
        return [call for call in self.calls if call[0] == "issue" and call[1] in kinds]

    # -- GraphQL ------------------------------------------------------------

    def discovered(self) -> list[dict]:
        return sorted((i for i in self.issues if "oc-discovered" in i["labels"]), key=lambda i: i["number"])

    def graphql_page(self, args: list[str]) -> dict:
        fields = dict(arg.split("=", 1) for arg in args[2:] if "=" in arg)
        assert fields["label"] == "oc-discovered"
        first = int(fields["first"])
        start = int(fields.get("cursor", "0"))
        collection = self.discovered()
        window = collection[start:start + first]
        end = start + len(window)
        return {
            "data": {
                "repository": {
                    "issues": {
                        "totalCount": len(collection),
                        "pageInfo": {"hasNextPage": end < len(collection), "endCursor": str(end) if window else None},
                        "nodes": [self.node(issue) for issue in window],
                    }
                }
            }
        }

    @staticmethod
    def node(issue: dict) -> dict:
        names = sorted(issue["labels"])
        return {
            "number": issue["number"],
            "state": issue["state"],
            "stateReason": issue["stateReason"],
            "body": issue["body"],
            "labels": {"totalCount": len(names), "nodes": [{"name": n} for n in names]},
        }

    # -- transport ----------------------------------------------------------

    def __call__(self, args, payload=None):
        self.calls.append(copy.deepcopy(args))
        if args[:2] == ["label", "create"]:
            return None
        if args[:2] == ["api", "graphql"]:
            return self.graphql_page(args)
        if args[:2] == ["issue", "list"]:
            assert "--search" in args and "--label" not in args
            token = args[args.index("--search") + 1].split('"')[1]
            limit = int(args[args.index("--limit") + 1])
            visible = [] if self.search_lags else [i for i in self.issues if i["number"] in self.indexed]
            hits = [i for i in visible if token in i["body"]][:limit]
            return [{**self.node(i), "labels": [{"name": n} for n in sorted(i["labels"])]} for i in hits]
        if args[:2] == ["issue", "create"]:
            if self.fail_create:
                raise subprocess.SubprocessError("redacted")
            labels = [args[k + 1] for k, a in enumerate(args) if a == "--label"]
            issue = self.add(args[args.index("--body") + 1], labels=tuple(labels))
            return f"https://github.com/{REPO}/issues/{issue['number']}"
        if args[:2] == ["issue", "reopen"]:
            issue = self.get(int(args[2]))
            issue["state"], issue["stateReason"] = "OPEN", "REOPENED"
            return ""
        if args[:2] == ["issue", "edit"]:
            issue = self.get(int(args[2]))
            for k, a in enumerate(args):
                if a == "--remove-label":
                    issue["labels"].discard(args[k + 1])
                if a == "--add-label":
                    issue["labels"].add(args[k + 1])
            return ""
        if args[:2] == ["issue", "view"]:
            issue = self.get(int(args[2]))
            return {"state": issue["state"], "labels": [{"name": n} for n in sorted(issue["labels"])]}
        if args[:2] == ["issue", "comment"]:
            return ""
        raise AssertionError(f"unexpected call {args}")


def run_pass(transport: FakeGitHub, discovery: dict, *, max_new: int = 3) -> dict:
    """Exactly what `main --apply` does, against the fake."""
    index = materialize.scan_discovered_issues(REPO, call=transport)
    planned = materialize.plan(
        discovery, index, max_new=max_new, max_cleared=max_new,
        search=lambda fp: materialize.search_fingerprint(REPO, fp, call=transport),
    )
    return materialize.apply_plan(planned, REPO, dry_run=False, call=transport)


def resolve(transport: FakeGitHub, number: int) -> None:
    """What hosted completion does on settlement: closed completed, oc-done."""
    issue = transport.get(number)
    issue["state"], issue["stateReason"] = "CLOSED", "COMPLETED"
    issue["labels"] = (issue["labels"] - {"oc-queued", "oc-running", "oc-validating"}) | {"oc-done"}


class TestIdentityIsTheCondition:
    def test_a_fresh_candidate_is_filed(self) -> None:
        transport = FakeGitHub()
        result = run_pass(transport, report(candidate()))
        assert result["created_count"] == 1
        assert result["results"][0]["issue_number"] == 1

    def test_the_second_pass_over_an_unchanged_repository_files_nothing(self) -> None:
        transport = FakeGitHub()
        run_pass(transport, report(candidate()))
        second = run_pass(transport, report(candidate()))
        assert second["planned_count"] == 0
        assert len(transport.writes("create")) == 1

    def test_an_open_lineage_is_in_flight_not_refiled(self) -> None:
        transport = FakeGitHub([{"body": filed(), "labels": ("oc-discovered", "oc-blocked")}])
        index = materialize.scan_discovered_issues(REPO, call=transport)
        planned = materialize.plan(report(candidate()), index)
        assert planned["action_count"] == 0
        assert planned["skipped"][0]["reason"] == "lineage_open"

    def test_a_race_between_two_waves_files_once(self) -> None:
        transport = FakeGitHub()
        planned = materialize.plan(report(candidate()), {})
        materialize.apply_plan(planned, REPO, dry_run=False, call=transport)
        # The loser planned against a stale snapshot and re-reads before writing.
        again = materialize.apply_plan(planned, REPO, dry_run=False, call=transport)
        assert again["results"][0]["outcome"] == "already_filed"
        assert len(transport.writes("create")) == 1

    def test_a_malformed_fingerprint_is_never_filed(self) -> None:
        planned = materialize.plan(report(candidate(fingerprint="nope")), {})
        assert planned["action_count"] == 0
        assert planned["skipped"][0]["reason"] == "unusable_fingerprint"

    def test_the_round_trip_body_is_readable_by_the_scan(self) -> None:
        transport = FakeGitHub()
        run_pass(transport, report(candidate()))
        assert set(materialize.scan_discovered_issues(REPO, call=transport)) == {FP}


class TestTheWholeHistoryIsRead:
    """The defect: a 1,000-issue lookup window, past which conditions re-file."""

    @staticmethod
    def crowded(total: int, *, target_at: int = 1) -> FakeGitHub:
        issues = [
            {"body": filed(FP if n == target_at else f"{n:016x}"), "state": "CLOSED", "reason": "COMPLETED",
             "labels": ("oc-discovered", "oc-done")}
            for n in range(1, total + 1)
        ]
        return FakeGitHub(issues)

    def test_a_fingerprint_older_than_a_thousand_discovered_issues_is_still_found(self) -> None:
        transport = self.crowded(1_250, target_at=1)
        result = run_pass(transport, report(candidate()))
        assert result["created_count"] == 0
        assert len(transport.of(FP)) == 1
        pages = [call for call in transport.calls if call[:2] == ["api", "graphql"]]
        scans = sum(not any(arg.startswith("cursor=") for arg in call) for call in pages)
        # Every scan walks ceil(1250 / 100) = 13 pages, through the last one.
        assert scans >= 1
        assert len(pages) == 13 * scans
        assert any("cursor=1200" in call for call in pages)

    def test_the_scan_indexes_every_issue_however_many_there_are(self) -> None:
        index = materialize.scan_discovered_issues(REPO, call=self.crowded(2_345))
        assert len(index) == 2_345

    def test_there_is_no_lookup_horizon_left_to_raise(self) -> None:
        assert not hasattr(materialize, "FINGERPRINT_LOOKUP_LIMIT")
        transport = self.crowded(5)
        materialize.scan_discovered_issues(REPO, call=transport)
        assert all("--limit" not in call for call in transport.calls)

    def test_the_scan_reads_closed_issues_too(self) -> None:
        assert "states: [OPEN, CLOSED]" in materialize.ISSUES_QUERY

    def test_a_page_that_promises_more_and_returns_nothing_fails_closed(self) -> None:
        class Stalls(FakeGitHub):
            def graphql_page(self, args):
                page = super().graphql_page(args)
                if "cursor=100" in args:
                    page["data"]["repository"]["issues"]["nodes"] = []
                return page

        transport = Stalls(self.crowded(250).issues)
        with pytest.raises(materialize.IncompleteHistory):
            materialize.scan_discovered_issues(REPO, call=transport)

    def test_a_cursor_that_does_not_advance_fails_closed(self) -> None:
        class Loops(FakeGitHub):
            def graphql_page(self, args):
                page = super().graphql_page(args)
                page["data"]["repository"]["issues"]["pageInfo"]["endCursor"] = "100"
                return page

        with pytest.raises(materialize.IncompleteHistory, match="cursor_did_not_advance"):
            materialize.scan_discovered_issues(REPO, call=Loops(self.crowded(350).issues))

    def test_fewer_issues_than_the_server_counted_fails_closed(self) -> None:
        class Short(FakeGitHub):
            def graphql_page(self, args):
                page = super().graphql_page(args)
                page["data"]["repository"]["issues"]["totalCount"] += 1
                return page

        with pytest.raises(materialize.IncompleteHistory, match="count_mismatch"):
            materialize.scan_discovered_issues(REPO, call=Short(self.crowded(150).issues))

    def test_a_collection_that_grows_during_the_read_fails_closed(self) -> None:
        class Grows(FakeGitHub):
            def graphql_page(self, args):
                if "cursor=100" in args:
                    self.add(filed("f" * 16))
                return super().graphql_page(args)

        with pytest.raises(materialize.IncompleteHistory, match="count_mismatch"):
            materialize.scan_discovered_issues(REPO, call=Grows(self.crowded(150).issues))

    def test_graphql_errors_fail_closed(self) -> None:
        class Errors(FakeGitHub):
            def graphql_page(self, args):
                return {**super().graphql_page(args), "errors": [{"message": "redacted"}]}

        with pytest.raises(materialize.IncompleteHistory, match="graphql_error"):
            materialize.scan_discovered_issues(REPO, call=Errors(self.crowded(3).issues))

    def test_an_unresolvable_node_fails_closed_rather_than_being_skipped(self) -> None:
        class NullNode(FakeGitHub):
            def graphql_page(self, args):
                page = super().graphql_page(args)
                page["data"]["repository"]["issues"]["nodes"][0] = None
                return page

        with pytest.raises(materialize.IncompleteHistory):
            materialize.scan_discovered_issues(REPO, call=NullNode(self.crowded(3).issues))

    def test_a_scan_failure_part_way_through_files_nothing(self) -> None:
        """A partial read is a smaller known set, which is how duplicates are filed."""

        class DiesOnPageThree(FakeGitHub):
            def graphql_page(self, args):
                if "cursor=200" in args:
                    raise subprocess.CalledProcessError(1, ["gh"])
                return super().graphql_page(args)

        transport = DiesOnPageThree(self.crowded(1_250, target_at=1_100).issues)
        with pytest.raises(subprocess.CalledProcessError):
            run_pass(transport, report(candidate()))
        assert transport.writes("create", "reopen", "edit") == []

    def test_a_failed_rescan_before_the_write_files_nothing(self) -> None:
        class DiesLater(FakeGitHub):
            scans = 0

            def graphql_page(self, args):
                if "cursor=" not in " ".join(args):
                    self.scans += 1
                if self.scans > 1:
                    raise subprocess.CalledProcessError(1, ["gh"])
                return super().graphql_page(args)

        transport = DiesLater()
        result = run_pass(transport, report(candidate()))
        assert result["created_count"] == 0
        assert result["errors"][0]["reason"] == "materialization_unconfirmed"
        assert transport.writes("create") == []

    def test_a_failed_search_files_nothing(self) -> None:
        class SearchDown(FakeGitHub):
            def __call__(self, args, payload=None):
                if args[:2] == ["issue", "list"]:
                    raise subprocess.CalledProcessError(1, ["gh"])
                return super().__call__(args, payload)

        transport = SearchDown()
        with pytest.raises(subprocess.CalledProcessError):
            run_pass(transport, report(candidate()))
        assert transport.writes("create") == []

    def test_a_search_result_at_the_ceiling_is_not_read_as_complete(self) -> None:
        issues = [{"body": filed(), "labels": ("oc-queued",)}
                  for _ in range(materialize.FINGERPRINT_SEARCH_CEILING)]
        with pytest.raises(materialize.IncompleteHistory, match="search_ceiling_reached"):
            materialize.search_fingerprint(REPO, FP, call=FakeGitHub(issues))


class TestDedupeSurvivesASlowSearchIndex:
    """The filing loop this module would otherwise run every five minutes.

    The search index is asynchronously maintained. The first implementation
    used it alone, so while an issue was unindexed every controller pass
    re-filed its condition -- including the re-check before the write, which
    asked the same lagging index. Four passes produced four identical issues.
    """

    def test_one_issue_across_many_waves_though_search_never_indexes_it(self) -> None:
        transport = FakeGitHub(search_lags=True)
        for _ in range(6):
            run_pass(transport, report(candidate()))
        assert len(transport.writes("create")) == 1
        assert len(transport.of(FP)) == 1

    def test_a_lagging_index_with_a_long_history_still_files_once(self) -> None:
        transport = FakeGitHub(TestTheWholeHistoryIsRead.crowded(1_050, target_at=2).issues, search_lags=True)
        fresh = "e" * 16
        for _ in range(4):
            run_pass(transport, report(candidate(), candidate(fresh)))
        assert len(transport.of(fresh)) == 1
        assert len(transport.of(FP)) == 1

    def test_search_still_catches_an_issue_whose_label_was_removed(self) -> None:
        """The scan cannot see it; that is why the targeted search stays."""
        transport = FakeGitHub([{"body": filed(), "labels": ("oc-queued",)}])
        result = run_pass(transport, report(candidate()))
        assert result["planned_count"] == 0
        assert transport.writes("create", "reopen", "edit") == []

    def test_the_search_asks_about_one_fingerprint_and_reads_closed_issues(self) -> None:
        transport = FakeGitHub()
        materialize.search_fingerprint(REPO, FP, call=transport)
        (call,) = transport.calls
        assert call[call.index("--search") + 1] == f'"{FP}" in:body'
        assert call[call.index("--state") + 1] == "all"

    def test_no_search_is_spent_on_a_candidate_this_pass_cannot_file(self) -> None:
        transport = FakeGitHub()
        many = [candidate(fingerprint=f"{n:016x}") for n in range(10)]
        run_pass(transport, report(*many), max_new=3)
        searches = [call for call in transport.calls if call[:2] == ["issue", "list"]]
        assert len(searches) == 3 + 3  # plan: three candidates; apply: one re-check each


class TestRecurrence:
    """Decision B -- requeue the lineage -- with the limits that keep it safe."""

    def resolved_lineage(self) -> FakeGitHub:
        transport = FakeGitHub()
        run_pass(transport, report(candidate()))
        resolve(transport, 1)
        return transport

    def test_a_condition_still_present_after_resolution_is_not_requeued(self) -> None:
        """Otherwise validate -> close -> requeue loops every five minutes."""
        transport = self.resolved_lineage()
        for _ in range(5):
            index = materialize.scan_discovered_issues(REPO, call=transport)
            planned = materialize.plan(report(candidate()), index)
            assert planned["skipped"][0]["reason"] == "resolved_condition_persists"
            materialize.apply_plan(planned, REPO, dry_run=False, call=transport)
        assert transport.writes("reopen", "edit") == []
        assert len(transport.of(FP)) == 1

    def test_absence_then_presence_requeues_the_same_issue(self) -> None:
        transport = self.resolved_lineage()
        cleared = run_pass(transport, report())  # the condition is gone
        assert cleared["cleared_count"] == 1
        assert "oc-condition-cleared" in transport.get(1)["labels"]

        recurred = run_pass(transport, report(candidate()))  # and back
        assert recurred["requeued_count"] == 1
        assert recurred["created_count"] == 0
        issue = transport.get(1)
        assert issue["state"] == "OPEN"
        assert "oc-queued" in issue["labels"]
        assert not issue["labels"] & {"oc-done", "oc-condition-cleared"}
        assert len(transport.of(FP)) == 1
        receipt = transport.writes("comment")[0]
        assert f"{materialize.RECURRENCE_MARKER}: {FP}" in receipt[receipt.index("--body") + 1]

    def test_a_requeued_lineage_is_in_flight_on_the_next_pass(self) -> None:
        transport = self.resolved_lineage()
        run_pass(transport, report())
        run_pass(transport, report(candidate()))
        before = len(transport.calls)
        after = run_pass(transport, report(candidate()))
        assert after["planned_count"] == 0
        assert all(call[1] not in {"create", "reopen", "edit"} for call in transport.calls[before:]
                   if call[0] == "issue")

    def test_each_requeue_needs_a_fresh_absence(self) -> None:
        transport = self.resolved_lineage()
        run_pass(transport, report())
        run_pass(transport, report(candidate()))
        resolve(transport, 1)  # resolved again, condition still present
        for _ in range(3):
            run_pass(transport, report(candidate()))
        assert len(transport.writes("reopen")) == 1

    def test_absence_from_a_source_that_did_not_run_proves_nothing(self) -> None:
        transport = self.resolved_lineage()
        result = run_pass(transport, report(sources=("undeclared-import",)))
        assert result["cleared_count"] == 0
        assert "oc-condition-cleared" not in transport.get(1)["labels"]

    def test_a_report_that_does_not_name_its_sources_proves_no_absence(self) -> None:
        transport = self.resolved_lineage()
        legacy = report()
        del legacy["sources_evaluated"]
        assert run_pass(transport, legacy)["cleared_count"] == 0

    def test_an_open_done_lineage_is_relabelled_without_a_reopen(self) -> None:
        transport = FakeGitHub([{"body": filed(), "labels": ("oc-discovered", "oc-done")}])
        run_pass(transport, report())
        result = run_pass(transport, report(candidate()))
        assert result["requeued_count"] == 1
        assert transport.writes("reopen") == []

    @pytest.mark.parametrize(
        ("state", "reason", "labels", "body_extra", "why"),
        [
            ("CLOSED", "NOT_PLANNED", ("oc-discovered", "oc-condition-cleared"), "", "closed_not_planned"),
            ("CLOSED", "COMPLETED", ("oc-discovered", "oc-done", "oc-condition-cleared"),
             "\nOC-AUTO-REQUEUE: false", "auto_requeue_disabled"),
            ("OPEN", None, ("oc-discovered", "oc-owner-gate"), "", "owner_hold"),
            ("CLOSED", "COMPLETED", ("oc-done", "oc-condition-cleared"), "", "discovered_label_removed"),
            ("CLOSED", None, ("oc-discovered", "oc-condition-cleared"), "", "closure_not_proven_complete"),
        ],
    )
    def test_a_rejected_lineage_stays_suppressed(self, state, reason, labels, body_extra, why) -> None:
        transport = FakeGitHub([{"body": filed() + body_extra, "state": state, "reason": reason,
                                 "labels": labels}])
        for _ in range(3):
            run_pass(transport, report())
            run_pass(transport, report(candidate()))
        index = materialize.scan_discovered_issues(REPO, call=transport)
        planned = materialize.plan(
            report(candidate()), index,
            search=lambda fp: materialize.search_fingerprint(REPO, fp, call=transport),
        )
        assert planned["skipped"][0]["reason"] == why
        assert transport.writes("create", "reopen", "edit", "comment") == []

    def test_a_closed_duplicate_defers_to_the_issue_it_duplicates(self) -> None:
        transport = FakeGitHub([
            {"body": filed(), "state": "CLOSED", "reason": "COMPLETED", "labels": ("oc-discovered", "oc-done")},
            {"body": filed(), "state": "CLOSED", "reason": "DUPLICATE", "labels": ("oc-discovered",)},
        ])
        run_pass(transport, report())
        result = run_pass(transport, report(candidate()))
        assert result["requeued_count"] == 1
        assert result["results"][0]["issue_number"] == 1

    def test_requeues_count_toward_the_same_bound_as_new_issues(self) -> None:
        old = [{"body": filed(f"{n:016x}"), "state": "CLOSED", "reason": "COMPLETED",
                "labels": ("oc-discovered", "oc-done", "oc-condition-cleared")} for n in range(1, 3)]
        transport = FakeGitHub(old)
        fresh = [candidate(fingerprint=f"{n:016x}") for n in range(10, 14)]
        recurring = [candidate(fingerprint=f"{n:016x}") for n in range(1, 3)]
        result = run_pass(transport, report(*recurring, *fresh), max_new=3)
        assert result["requeued_count"] + result["created_count"] == 3

    def test_an_unconfirmed_requeue_is_an_error_not_a_success(self) -> None:
        class Sticky(FakeGitHub):
            def __call__(self, args, payload=None):
                if args[:2] == ["issue", "edit"] and "--add-label" in args and "oc-queued" in args:
                    self.calls.append(copy.deepcopy(args))
                    return ""
                return super().__call__(args, payload)

        transport = Sticky([{"body": filed(), "state": "CLOSED", "reason": "COMPLETED",
                             "labels": ("oc-discovered", "oc-done", "oc-condition-cleared")}])
        result = run_pass(transport, report(candidate()))
        assert result["requeued_count"] == 0
        assert result["errors"][0]["reason"] == "materialization_unconfirmed"
        assert transport.writes("comment") == []

    def test_a_lineage_that_changed_after_planning_is_left_alone(self) -> None:
        transport = FakeGitHub([{"body": filed(), "state": "CLOSED", "reason": "COMPLETED",
                                 "labels": ("oc-discovered", "oc-done", "oc-condition-cleared")}])
        planned = materialize.plan(report(candidate()), materialize.scan_discovered_issues(REPO, call=transport))
        transport.get(1)["labels"].add("oc-owner-gate")  # a person intervened
        result = materialize.apply_plan(planned, REPO, dry_run=False, call=transport)
        assert result["results"][0]["outcome"] == "lineage_changed"
        assert transport.writes("reopen", "edit") == []


class TestBounded:
    def test_a_pass_files_at_most_max_new(self) -> None:
        candidates = [candidate(fingerprint=f"{index:016x}") for index in range(10)]
        planned = materialize.plan(report(*candidates), {}, max_new=3)
        assert planned["action_count"] == 3
        assert sum(row["reason"] == "bounded_by_max_new" for row in planned["skipped"]) == 7

    def test_the_highest_ranked_candidates_are_the_ones_filed(self) -> None:
        low = candidate(fingerprint="b" * 16, rank=5, lane=None)
        high = candidate(fingerprint="c" * 16, rank=1)
        planned = materialize.plan(report(high, low), {}, max_new=1)
        assert planned["actions"][0]["fingerprint"] == "c" * 16

    def test_clearance_marks_are_bounded_too(self) -> None:
        old = [{"body": filed(f"{n:016x}"), "state": "CLOSED", "reason": "COMPLETED",
                "labels": ("oc-discovered", "oc-done")} for n in range(1, 8)]
        transport = FakeGitHub(old)
        assert run_pass(transport, report(), max_new=3)["cleared_count"] == 3

    def test_dry_run_is_the_default_and_writes_nothing(self) -> None:
        transport = FakeGitHub()
        result = materialize.apply_plan(materialize.plan(report(candidate()), {}), REPO, call=transport)
        assert result["dry_run"] is True
        assert result["created_count"] == 0
        assert transport.calls == []


class TestTheIssueItFiles:
    def test_the_body_carries_the_fingerprint_and_the_swarm_markers(self) -> None:
        body = materialize.issue_body(candidate())
        assert materialize.FINGERPRINT.search(body)
        assert "OC-SWARM-CAPABILITY: test-execution" in body
        assert "OC-SWARM-READS: control-plane" in body

    def test_the_body_names_its_source_so_absence_can_be_judged(self) -> None:
        body = materialize.issue_body(candidate())
        assert materialize.DISCOVERY_SOURCE.search(body).group("source") == "dependency-gap"

    def test_the_body_carries_every_piece_of_evidence(self) -> None:
        assert "tests/test_calyx_brain_x.py" in materialize.issue_body(candidate())

    def test_an_unbound_candidate_says_so_rather_than_naming_a_lane(self) -> None:
        body = materialize.issue_body(candidate(lane=None))
        assert "UNBOUND" in body
        assert "Product lane: Calyx" not in body

    def test_the_body_says_no_person_selected_it(self) -> None:
        assert "No person selected it" in materialize.issue_body(candidate())


class TestFailClosed:
    def test_an_unrecognised_report_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unrecognised discovery report"):
            materialize.plan({"schema": "something.else"}, {})

    def test_an_invalid_repository_is_refused(self) -> None:
        with pytest.raises(ValueError, match="invalid repository"):
            materialize.apply_plan(materialize.plan(report(), {}), "not a repo", dry_run=False)
        with pytest.raises(ValueError, match="invalid repository"):
            materialize.scan_discovered_issues("not a repo", call=FakeGitHub())

    def test_one_failed_creation_does_not_stop_the_rest(self) -> None:
        transport = FakeGitHub()
        transport.fail_create = True
        result = run_pass(transport, report(candidate()))
        assert result["created_count"] == 0
        assert result["errors"][0]["reason"] == "materialization_unconfirmed"

    def test_a_creation_that_returns_no_url_is_not_reported_as_created(self) -> None:
        class NoUrl(FakeGitHub):
            def __call__(self, args, payload=None):
                if args[:2] == ["issue", "create"]:
                    self.calls.append(args)
                    return "something that is not a url"
                return super().__call__(args, payload)

        result = run_pass(NoUrl(), report(candidate()))
        assert result["created_count"] == 0
        assert result["errors"]


def test_the_plan_is_json_serialisable_for_the_workflow() -> None:
    json.dumps(materialize.plan(report(candidate()), {}))


class TestLabelsExistBeforeTheWrite:
    def test_every_label_is_created_before_the_issue(self) -> None:
        """A label the repository lacks fails `gh issue create` outright."""
        transport = FakeGitHub()
        run_pass(transport, report(candidate()))
        kinds = [call[:2] for call in transport.calls]
        assert kinds.index(["label", "create"]) < kinds.index(["issue", "create"])

    def test_each_of_the_four_labels_is_ensured(self) -> None:
        transport = FakeGitHub()
        run_pass(transport, report(candidate()))
        created = {call[2] for call in transport.calls if call[:2] == ["label", "create"]}
        assert created == {"oc-queued", "oc-p1", "oc-discovered", "oc-lane:calyx"}

    def test_creation_is_idempotent(self) -> None:
        transport = FakeGitHub()
        run_pass(transport, report(candidate()))
        assert all("--force" in call for call in transport.calls if call[:2] == ["label", "create"])

    def test_a_label_outside_this_modules_vocabulary_is_refused(self) -> None:
        with pytest.raises(ValueError, match="outside this module's vocabulary"):
            materialize.ensure_labels(REPO, ["something-someone-typoed"], call=FakeGitHub())

    def test_the_clearance_label_is_this_modules_own(self) -> None:
        assert materialize.ensure_labels(REPO, ["oc-condition-cleared"], call=FakeGitHub())

    def test_any_lane_label_is_allowed_because_the_table_owns_that_shape(self) -> None:
        assert materialize.ensure_labels(REPO, ["oc-lane:vision-lab"], call=FakeGitHub()) == [
            "oc-lane:vision-lab"
        ]


class TestMain:
    def write(self, tmp_path: Path, discovery: dict) -> Path:
        path = tmp_path / "discovery.json"
        path.write_text(json.dumps(discovery), encoding="utf-8")
        return path

    def test_apply_scans_files_and_reports_to_the_workflow(self, tmp_path, monkeypatch, capsys) -> None:
        transport = FakeGitHub(TestTheWholeHistoryIsRead.crowded(1_100).issues, search_lags=True)
        monkeypatch.setattr(materialize, "github", transport)
        output = tmp_path / "out"
        path = self.write(tmp_path, report(candidate(), candidate("d" * 16)))
        for _ in range(3):
            assert materialize.main(["--repository", REPO, "--report", str(path), "--apply",
                                     "--github-output", str(output)]) == 0
        capsys.readouterr()
        assert len(transport.of("d" * 16)) == 1
        assert len(transport.of(FP)) == 1
        lines = output.read_text().splitlines()
        assert lines[:4] == ["created_count=1", "created_numbers=[1101]", "requeued_count=0", "requeued_numbers=[]"]

    def test_an_incomplete_scan_stops_main_before_any_write(self, tmp_path, monkeypatch) -> None:
        class Broken(FakeGitHub):
            def graphql_page(self, args):
                return {"errors": [{"message": "redacted"}]}

        transport = Broken()
        monkeypatch.setattr(materialize, "github", transport)
        with pytest.raises(materialize.IncompleteHistory):
            materialize.main(["--repository", REPO, "--report", str(self.write(tmp_path, report(candidate()))),
                              "--apply"])
        assert transport.writes("create") == []

    def test_a_dry_run_reads_and_writes_nothing(self, tmp_path, monkeypatch, capsys) -> None:
        transport = FakeGitHub()
        monkeypatch.setattr(materialize, "github", transport)
        materialize.main(["--repository", REPO, "--report", str(self.write(tmp_path, report(candidate())))])
        assert json.loads(capsys.readouterr().out)["dry_run"] is True
        assert transport.calls == []
