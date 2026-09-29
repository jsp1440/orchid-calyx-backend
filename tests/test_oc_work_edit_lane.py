"""The edit lane writes one line it can prove, and refuses everything else.

Most of these tests are refusals, because the failure mode of a lane that edits
code is not a missing edit -- it is a confident wrong one. The two end-to-end
tests drive real git: a tiny repository with a fake validator, and this
repository itself with the pytest-asyncio gap re-created and the real
``calyx-async-acceptance`` command run before and after.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import oc_work_discovery as discovery
from scripts import oc_work_edit_lane as lane
from scripts import oc_work_materialize as materialize

ROOT = Path(__file__).resolve().parents[1]
REPO = "jsp1440/orchid-calyx-backend"
FP = "2805f85430b3a402"
BASE_SHA = "0" * 40


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


worker = _script("oc_swarm_provider_free_worker")


def candidate(
    *,
    source: str = "dependency-gap",
    distribution: str = "pytest-asyncio",
    command: str = "control-plane-compiles",
    fingerprint: str = FP,
    remedy: bool = True,
) -> dict:
    record = {
        "schema": "oc.work-candidate.v1",
        "source": source,
        "title": f"Declare {distribution}",
        "summary": "A marker's distribution is undeclared.",
        "lane": "calyx",
        "lane_name": "Calyx",
        "rank": 1,
        "analysis_only": False,
        "fingerprint": fingerprint,
        "semantic_key": f"{source}:{distribution}",
        "proposed_remedy": "Add a pinned requirement.",
        "remedy": (
            {
                "kind": "declare-distribution",
                "distribution": distribution,
                "requirements_file": discovery.MECHANICAL_SOURCES.get(
                    source, "requirements-dev.txt"
                ),
                "installed_version": None,
            }
            if remedy
            else {}
        ),
        "capabilities": ["test-execution"],
        "validation_command": command,
        "labels": ["oc-queued", "oc-p1", "oc-discovered", "oc-lane:calyx"],
        "evidence": [
            {
                "kind": "marker-without-distribution",
                "where": "tests/test_calyx_brain_x.py",
                "detail": "d",
            }
        ],
    }
    return record


def issue_for(cand: dict, number: int = 9000) -> dict:
    return {
        "number": number,
        "state": "OPEN",
        "title": cand["title"],
        "body": materialize.issue_body(cand),
    }


class FakeGitHub:
    """`gh pr list` and `gh pr create`, with a body-indexed PR store."""

    def __init__(self) -> None:
        self.prs: list[dict] = []
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], payload: dict | None = None):
        self.calls.append(list(args))
        if args[:2] == ["pr", "list"]:
            return [dict(pr) for pr in self.prs]
        if args[:2] == ["pr", "create"]:
            number = 100 + len(self.prs)
            body = args[args.index("--body") + 1]
            head = args[args.index("--head") + 1]
            pr = {
                "number": number,
                "url": f"https://github.com/{REPO}/pull/{number}",
                "headRefName": head,
                "body": body,
                "title": args[args.index("--title") + 1],
                "base": args[args.index("--base") + 1],
                "draft": "--draft" in args,
            }
            self.prs.append(pr)
            return pr["url"]
        raise AssertionError(f"unexpected gh call {args}")


def completed(argv, returncode: int, stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(list(argv), returncode, stdout=stdout, stderr="")


BEFORE_OUTPUT = (
    "FAILED tests/test_calyx_brain_x.py::test_one - async def functions are not natively supported\n"
    "FAILED tests/test_calyx_brain_x.py::test_two - async def functions are not natively supported\n"
    "2 failed, 1 passed in 0.10s\n"
)
AFTER_OUTPUT = "3 passed in 0.10s\n"


# -- Derivation ----------------------------------------------------------------


class TestDerivation:
    def test_the_line_is_the_installed_version_pinned(self, tmp_path: Path) -> None:
        (tmp_path / "requirements-dev.txt").write_text("pytest==9.1.1\n")
        edit = lane.derive_edit(candidate(), tmp_path, version_of=lambda name: "1.4.0")
        assert edit.path == "requirements-dev.txt"
        assert edit.line == "pytest-asyncio==1.4.0"
        assert edit.validation_command == "control-plane-compiles"

    def test_undeclared_import_goes_to_the_production_file(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "requirements.txt").write_text("fastapi<0.116\n")
        edit = lane.derive_edit(
            candidate(source="undeclared-import", distribution="starlette"),
            tmp_path,
            version_of=lambda name: "0.46.2",
        )
        assert edit.path == "requirements.txt"
        assert edit.line == "starlette==0.46.2"

    @pytest.mark.parametrize(
        ("cand", "version", "reason"),
        [
            (candidate(source="failing-test"), "1.0", "unsupported_source"),
            (candidate(source="binding-gap"), "1.0", "unsupported_source"),
            (candidate(remedy=False), "1.0", "no_structured_remedy"),
            (candidate(command=""), "1.0", "no_validation_command"),
            (
                candidate(command="not-a-registered-command"),
                "1.0",
                "no_validation_command",
            ),
            (candidate(fingerprint="nope"), "1.0", "unusable_fingerprint"),
            (candidate(), None, "distribution_not_installed"),
            (candidate(), "1.4.0+local.build", "version_unparseable"),
            (candidate(), "not a version", "version_unparseable"),
            (candidate(distribution="bad name!"), "1.0", "invalid_distribution_name"),
        ],
    )
    def test_refusals_name_what_was_missing(
        self, tmp_path: Path, cand, version, reason
    ) -> None:
        (tmp_path / "requirements-dev.txt").write_text("pytest==9.1.1\n")
        with pytest.raises(lane.LaneRefusal) as caught:
            lane.derive_edit(cand, tmp_path, version_of=lambda name: version)
        assert caught.value.reason == reason

    def test_a_declaration_anywhere_is_a_refusal(self, tmp_path: Path) -> None:
        # Declared in requirements.txt, not the file this source would edit:
        # still declared, still not this lane's to write twice.
        (tmp_path / "requirements.txt").write_text("pytest_asyncio[extra]>=1\n")
        with pytest.raises(lane.LaneRefusal, match="already_declared"):
            lane.derive_edit(candidate(), tmp_path, version_of=lambda name: "1.4.0")

    @pytest.mark.parametrize(
        "spelling", ["pytest.asyncio==1.0", "Pytest.Asyncio", "pytest__asyncio>=1"]
    )
    def test_a_declaration_under_any_pep503_spelling_is_a_refusal(
        self, tmp_path: Path, spelling: str
    ) -> None:
        (tmp_path / "requirements-ci.txt").write_text(f"{spelling}\n")
        with pytest.raises(lane.LaneRefusal, match="already_declared"):
            lane.derive_edit(candidate(), tmp_path, version_of=lambda name: "1.4.0")

    def test_a_remedy_naming_the_wrong_file_is_refused(self, tmp_path: Path) -> None:
        cand = candidate()
        cand["remedy"]["requirements_file"] = "requirements.txt"
        with pytest.raises(lane.LaneRefusal, match="remedy_file_mismatch"):
            lane.derive_edit(cand, tmp_path, version_of=lambda name: "1.4.0")

    def test_never_latest(self, tmp_path: Path) -> None:
        """The version is asked of the environment; nothing here reads an index."""
        asked: list[str] = []

        def version_of(name: str) -> str | None:
            asked.append(name)
            return "1.4.0"

        edit = lane.derive_edit(candidate(), tmp_path, version_of=version_of)
        assert asked == ["pytest-asyncio"]
        assert "==" in edit.line and ">=" not in edit.line


class TestApply:
    def test_appends_one_pinned_line_with_the_fingerprint(self, tmp_path: Path) -> None:
        (tmp_path / "requirements-dev.txt").write_text(
            "pytest==9.1.1"
        )  # no trailing newline
        edit = lane.derive_edit(candidate(), tmp_path, version_of=lambda name: "1.4.0")
        assert lane.apply_edit(edit, tmp_path) is True
        text = (tmp_path / "requirements-dev.txt").read_text()
        assert text.endswith("pytest-asyncio==1.4.0\n")
        assert FP in text
        assert text.startswith("pytest==9.1.1\n")

    def test_applying_twice_writes_once(self, tmp_path: Path) -> None:
        (tmp_path / "requirements-dev.txt").write_text("pytest==9.1.1\n")
        edit = lane.derive_edit(candidate(), tmp_path, version_of=lambda name: "1.4.0")
        assert lane.apply_edit(edit, tmp_path) is True
        assert lane.apply_edit(edit, tmp_path) is False
        assert (tmp_path / "requirements-dev.txt").read_text().count(
            "pytest-asyncio=="
        ) == 1

    @pytest.mark.parametrize(
        "existing",
        [
            "Pytest_Asyncio>=0.1",
            "pytest.asyncio==1.4.0",
            "  pytest-asyncio ; python_version>'3'",
        ],
    )
    def test_any_pep503_spelling_already_declared_is_left_alone(
        self, tmp_path: Path, existing: str
    ) -> None:
        edit = lane.derive_edit(candidate(), tmp_path, version_of=lambda name: "1.4.0")
        (tmp_path / "requirements-dev.txt").write_text(f"pytest==9.1.1\n{existing}\n")
        assert lane.apply_edit(edit, tmp_path) is False
        assert (
            "pytest-asyncio==1.4.0"
            not in (tmp_path / "requirements-dev.txt").read_text()
        )


class TestJudgement:
    # A pytest-shaped command: its summary line is part of the result.
    def run(self, exit_code: int, output: str) -> dict:
        return lane.run_validation(
            "calyx-async-acceptance",
            cwd=".",
            runner=lambda argv, cwd, timeout: completed(argv, exit_code, output),
        )

    def test_before_failing_ids_must_pass_after(self) -> None:
        before = self.run(1, BEFORE_OUTPUT)
        assert before["failing_node_ids"] == [
            "tests/test_calyx_brain_x.py::test_one",
            "tests/test_calyx_brain_x.py::test_two",
        ]
        ok, why = lane.judge(before, self.run(0, AFTER_OUTPUT))
        assert ok, why

    def test_exit_zero_with_a_survivor_is_not_a_pass(self) -> None:
        # A run that exits 0 and still lists a failing id is contradictory;
        # the id wins, because it is the more specific statement.
        survivor = "FAILED tests/test_calyx_brain_x.py::test_one\n1 failed in 0.1s\n"
        ok, why = lane.judge(self.run(1, BEFORE_OUTPUT), self.run(0, survivor))
        assert not ok and "still fail" in why

    def test_a_non_zero_exit_after_the_edit_fails(self) -> None:
        ok, why = lane.judge(self.run(1, BEFORE_OUTPUT), self.run(1, BEFORE_OUTPUT))
        assert not ok and "exited 1" in why

    def test_a_run_without_a_summary_line_is_not_a_result(self) -> None:
        ok, why = lane.judge(
            self.run(1, BEFORE_OUTPUT), self.run(0, "collected nothing\n")
        )
        assert not ok and "inconclusive" in why

    def test_an_import_check_needs_no_summary_line(self) -> None:
        result = lane.run_validation(
            "production-runtime-imports",
            cwd=".",
            runner=lambda argv, cwd, timeout: completed(argv, 0, ""),
        )
        assert result["pytest_shaped"] is False and result["conclusive"] is True
        ok, _ = lane.judge(result, result)
        assert ok

    def test_a_timeout_is_a_failure(self) -> None:
        def runner(argv, cwd, timeout):
            raise subprocess.TimeoutExpired(list(argv), timeout, output=b"partial")

        result = lane.run_validation("control-plane-compiles", cwd=".", runner=runner)
        assert result["timed_out"] is True and result["passed"] is False


class TestReceiptFailsClosed:
    def good(self) -> dict:
        return {
            "schema": lane.RECEIPT_SCHEMA,
            "outcome": "pr_opened",
            "disposition": "blocked",
            "changed_file_count": 1,
            "changed_files": ["requirements-dev.txt"],
            "pr_number": 101,
            "commit_sha": "a" * 40,
            "diff_sha256": "b" * 64,
            "branch": lane.branch_name(FP),
            "pr_url": f"https://github.com/{REPO}/pull/101",
            "reason": "validation passed",
            "validation_passed": True,
            "fingerprint": FP,
            "issue_number": 9000,
            "validation_commands": ["control-plane-compiles"],
            "edit": {"path": "requirements-dev.txt", "line": "pytest-asyncio==1.4.0"},
            "before": {"command_id": "control-plane-compiles", "exit_code": 1},
            "after": {"command_id": "control-plane-compiles", "exit_code": 0},
            "safety": {"provider_calls": False, "push_to_main": False},
        }

    def test_a_complete_pr_receipt_passes(self) -> None:
        assert lane.finalize_receipt(self.good())["outcome"] == "pr_opened"

    @pytest.mark.parametrize(
        "broken",
        [
            {"pr_number": None},
            {"pr_number": 0},
            {"commit_sha": "abc"},
            {"commit_sha": None},
            {"diff_sha256": "short"},
            {"changed_file_count": 0, "changed_files": []},
            {"changed_file_count": 2, "changed_files": ["a", "b"]},
            {"branch": "main"},
            {"disposition": "done"},
            {"outcome": "merged"},
            {"schema": "something-else"},
            {"pr_url": None},
            {"pr_url": f"https://github.com/{REPO}/pull/102"},
            {"validation_passed": False},
            {"fingerprint": None},
            {"issue_number": None},
            {"issue_number": 0},
            {"validation_commands": []},
            {"edit": None},
            {"edit": {"path": "requirements.txt"}},
            {"before": None},
            {"after": None},
            {"after": {"command_id": "calyx-async-acceptance"}},
            {"reason": ""},
            {"safety": None},
            {"safety": {"push_to_main": True}},
        ],
    )
    def test_a_pr_receipt_missing_anything_is_refused(self, broken: dict) -> None:
        with pytest.raises(ValueError):
            lane.finalize_receipt({**self.good(), **broken})

    def test_a_refusal_may_not_claim_a_change(self) -> None:
        with pytest.raises(ValueError):
            lane.finalize_receipt(
                {**self.good(), "outcome": "refused", "changed_file_count": 1}
            )


class TestIdempotencyLookup:
    def test_only_a_body_carrying_the_marker_counts(self) -> None:
        gh = FakeGitHub()
        gh.prs = [
            {
                "number": 5,
                "url": "u",
                "headRefName": "x",
                "body": f"mentions {FP} in prose",
            },
            {
                "number": 7,
                "url": "u",
                "headRefName": lane.branch_name(FP),
                "body": f"{materialize.FINGERPRINT_MARKER}: {FP}",
            },
        ]
        found = lane.open_pull_requests(REPO, FP, call=gh)
        assert [pr["number"] for pr in found] == [7]
        assert "--state" in gh.calls[0] and "open" in gh.calls[0]

    def test_an_unreadable_search_fails_closed(self) -> None:
        with pytest.raises(materialize.IncompleteHistory):
            lane.open_pull_requests(REPO, FP, call=lambda args, payload: "not a list")


# -- The worker's edit mode ----------------------------------------------------


def lease_comment(writes: list[str] | None = None) -> str:
    return (
        "[OC-SWARM-V4] Dependency/resource lease claimed: `"
        f'{{"reads":[],"writes":{json.dumps(writes or [])}}}`.'
    )


#: requirements*.txt classify as repo-global, so a lane lease must write it.
LANE_LEASE = lease_comment(["repo-global"])


def edit_receipt(**over) -> dict:
    receipt = {
        "schema": lane.RECEIPT_SCHEMA,
        "outcome": "pr_opened",
        "disposition": "blocked",
        "validation_commands": ["control-plane-compiles"],
        "validation_passed": True,
        "changed_file_count": 1,
        "changed_files": ["requirements-dev.txt"],
        "pr_number": 101,
    }
    receipt.update(over)
    return receipt


class TestWorkerEditMode:
    def test_a_pull_request_parks_the_issue_on_that_pr(self) -> None:
        receipt = worker.build_receipt(
            issue_for(candidate()),
            lease_comment=lease_comment(["repo-global"]),
            changed_files=["requirements-dev.txt"],
            integration_sha="abc",
            edit=edit_receipt(),
        )
        assert receipt["mode"] == "edit"
        assert receipt["disposition"] == "blocked"
        assert receipt["blocked_on"] == "pr#101"
        assert receipt["changed_file_count"] == 1
        assert receipt["write_set"]["passed"] is True
        # It pushed a branch: the settlement may not say it wrote nothing.
        assert receipt["safety"]["repository_writes"] is True

    def test_the_verified_write_set_must_be_the_lanes_own(self) -> None:
        with pytest.raises(ValueError, match="differ from the edit lane"):
            worker.build_receipt(
                issue_for(candidate()),
                lease_comment=lease_comment(["repo-global"]),
                changed_files=[],
                integration_sha="abc",
                edit=edit_receipt(),
            )

    def test_the_issue_body_leases_the_write_the_lane_needs(self) -> None:
        body = issue_for(candidate())["body"]
        assert "OC-SWARM-PROVIDER-FREE: edit" in body
        assert "OC-SWARM-WRITES: repo-global" in body
        assert "OC-SWARM-VALIDATE: control-plane-compiles" in body

    def test_an_edit_outside_the_lease_fails_closed(self) -> None:
        with pytest.raises(ValueError, match="exceeds the durable lease"):
            worker.build_receipt(
                issue_for(candidate()),
                lease_comment=lease_comment([]),
                changed_files=["requirements-dev.txt"],
                integration_sha="abc",
                edit=edit_receipt(),
            )

    def test_an_absent_condition_proven_by_validation_settles_done(self) -> None:
        receipt = worker.build_receipt(
            issue_for(candidate()),
            lease_comment=lease_comment(),
            changed_files=[],
            integration_sha="abc",
            edit=edit_receipt(
                outcome="condition_absent_validated",
                changed_file_count=0,
                changed_files=[],
                pr_number=None,
                disposition="done",
            ),
        )
        assert receipt["disposition"] == "done" and receipt["blocked_on"] is None

    @pytest.mark.parametrize(
        "over",
        [
            {"outcome": "refused", "changed_file_count": 0, "pr_number": None},
            {
                "outcome": "validation_failed",
                "changed_file_count": 0,
                "pr_number": None,
            },
            {
                "outcome": "condition_absent_validated",
                "validation_passed": False,
                "changed_file_count": 0,
            },
            {"outcome": "something_new"},
        ],
    )
    def test_every_other_outcome_settles_blocked(self, over: dict) -> None:
        receipt = worker.build_receipt(
            issue_for(candidate()),
            lease_comment=lease_comment(["repo-global"]),
            changed_files=[],
            integration_sha="abc",
            edit=edit_receipt(**{"changed_files": [], **over}),
        )
        assert receipt["disposition"] == "blocked" and receipt["blocked_on"] is None

    @pytest.mark.parametrize(
        ("over", "message"),
        [
            ({"schema": "other"}, "schema"),
            ({"validation_commands": ["control-plane-tests"]}, "declared commands"),
            ({"pr_number": None}, "no pull request"),
        ],
    )
    def test_a_malformed_receipt_is_refused(self, over: dict, message: str) -> None:
        with pytest.raises(ValueError, match=message):
            worker.build_receipt(
                issue_for(candidate()),
                lease_comment=lease_comment(["repo-global"]),
                changed_files=[],
                integration_sha="abc",
                edit=edit_receipt(**over),
            )

    def test_a_non_integer_change_count_is_a_type_error(self) -> None:
        with pytest.raises(TypeError, match="changed_file_count"):
            worker.build_receipt(
                issue_for(candidate()),
                lease_comment=lease_comment(["repo-global"]),
                changed_files=[],
                integration_sha="abc",
                edit=edit_receipt(changed_file_count="1"),
            )

    def test_edit_mode_without_a_receipt_is_refused(self) -> None:
        with pytest.raises(ValueError, match="requires the edit lane"):
            worker.build_receipt(
                issue_for(candidate()),
                lease_comment=lease_comment(),
                changed_files=[],
                integration_sha="abc",
            )

    def test_validate_mode_may_not_carry_edit_evidence(self) -> None:
        body = "OC-SWARM-PROVIDER-FREE: validate\nOC-SWARM-VALIDATE: control-plane-compiles\nOC-SWARM-DISPOSITION: done"
        with pytest.raises(ValueError, match="does not carry edit-lane evidence"):
            worker.build_receipt(
                {"number": 1, "state": "OPEN", "body": body},
                lease_comment=lease_comment(),
                changed_files=[],
                integration_sha="abc",
                edit=edit_receipt(),
            )

    def test_the_plan_names_the_edit_executor(self) -> None:
        plan = worker.execution_plan(issue_for(candidate()))
        assert plan["mode"] == "edit" and plan["supported"] is True
        assert plan["commands"] == ["control-plane-compiles"]


# -- End to end on a tiny repository with real git ------------------------------


def _git(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture()
def tiny_repo(tmp_path: Path) -> tuple[Path, Path, str]:
    origin = tmp_path / "origin.git"
    _git(["init", "-q", "--bare", str(origin)], tmp_path)
    work = tmp_path / "work"
    _git(["clone", "-q", str(origin), str(work)], tmp_path)
    (work / "requirements-dev.txt").write_text("pytest==9.1.1\n")
    (work / "requirements.txt").write_text("fastapi<0.116\n")
    _git(["add", "."], work)
    _git(
        [
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-q",
            "-m",
            "base",
        ],
        work,
    )
    _git(["push", "-q", "-u", "origin", "HEAD:main"], work)
    return origin, work, _git(["rev-parse", "HEAD"], work)


def fake_runner_factory(state: dict):
    def runner(argv, cwd, timeout):
        text = (Path(cwd) / "requirements-dev.txt").read_text()
        fixed = "pytest-asyncio==" in text
        return completed(
            argv, 0 if fixed else 1, AFTER_OUTPUT if fixed else BEFORE_OUTPUT
        )

    return runner


class TestLaneEndToEnd:
    def run(
        self,
        tiny_repo,
        *,
        gh=None,
        version="1.4.0",
        provision=None,
        discover=None,
        cand=None,
        lease=LANE_LEASE,
    ):
        origin, work, base = tiny_repo
        cand = cand or candidate()
        gh = gh or FakeGitHub()
        receipt = lane.run_lane(
            issue_for(cand),
            repository=REPO,
            lease_comment=lease,
            root=work,
            base_sha=base,
            call=gh,
            git_call=lane.git,
            runner=fake_runner_factory({}),
            version_of=lambda name: version,
            provision=provision,
            discover=discover or (lambda root: {"candidates": [cand]}),
            worktree_root=work.parent,
        )
        return receipt, gh, origin, work, base

    def test_opens_one_draft_pr_with_the_evidence_and_leaves_the_checkout_alone(
        self, tiny_repo
    ) -> None:
        receipt, gh, origin, work, base = self.run(tiny_repo)
        assert receipt["outcome"] == "pr_opened" and receipt["disposition"] == "blocked"
        assert receipt["changed_file_count"] == 1 and receipt["changed_files"] == [
            "requirements-dev.txt"
        ]
        assert receipt["pr_number"] == 100 and receipt["branch"] == lane.branch_name(FP)
        # The commit is on the pushed branch, the checkout is untouched, and
        # the local lane branch and worktree are gone.
        assert (
            _git(["rev-parse", f"refs/heads/{receipt['branch']}"], origin)
            == receipt["commit_sha"]
        )
        assert _git(["rev-parse", "HEAD"], work) == base
        assert "pytest-asyncio" not in (work / "requirements-dev.txt").read_text()
        assert _git(["branch", "--list", receipt["branch"]], work) == ""
        assert _git(["worktree", "list"], work).count("\n") == 0
        pr = gh.prs[0]
        assert (
            pr["draft"]
            and pr["base"] == lane.DEFAULT_INTEGRATION_BRANCH
            and pr["headRefName"] == receipt["branch"]
        )
        assert f"{materialize.FINGERPRINT_MARKER}: {FP}" in pr["body"]
        assert "+pytest-asyncio==1.4.0" in pr["body"]
        assert (
            "tests/test_calyx_brain_x.py::test_one` — failed before, passes after"
            in pr["body"]
        )
        assert (
            receipt["before"]["output_digest"] in pr["body"]
            and receipt["after"]["output_digest"] in pr["body"]
        )
        import hashlib

        diff = _git(["diff", base, receipt["commit_sha"]], origin)
        assert receipt["diff_sha256"] == hashlib.sha256(diff.encode()).hexdigest()

    def test_a_second_pass_with_the_pr_open_files_nothing(self, tiny_repo) -> None:
        receipt, gh, _origin, work, base = self.run(tiny_repo)
        again = lane.run_lane(
            issue_for(candidate()),
            repository=REPO,
            lease_comment=LANE_LEASE,
            root=work,
            base_sha=base,
            call=gh,
            git_call=lane.git,
            runner=fake_runner_factory({}),
            version_of=lambda name: "1.4.0",
            provision=None,
            discover=lambda root: (_ for _ in ()).throw(
                AssertionError("must not read the tree")
            ),
        )
        assert (
            again["outcome"] == "already_open"
            and again["pr_number"] == receipt["pr_number"]
        )
        assert again["changed_file_count"] == 0
        assert (
            len(gh.prs) == 1 and [c[:2] for c in gh.calls].count(["pr", "create"]) == 1
        )

    def test_a_failed_validation_reverts_and_settles_blocked(self, tiny_repo) -> None:
        _origin, work, base = tiny_repo
        cand = candidate()
        gh = FakeGitHub()
        receipt = lane.run_lane(
            issue_for(cand),
            repository=REPO,
            lease_comment=LANE_LEASE,
            root=work,
            base_sha=base,
            call=gh,
            git_call=lane.git,
            runner=lambda argv, cwd, timeout: completed(argv, 1, BEFORE_OUTPUT),
            version_of=lambda name: "1.4.0",
            provision=None,
            discover=lambda root: {"candidates": [cand]},
        )
        assert (
            receipt["outcome"] == "validation_failed"
            and receipt["disposition"] == "blocked"
        )
        assert receipt["changed_file_count"] == 0 and receipt["pr_number"] is None
        assert (
            receipt["before"]["failing_node_ids"] and receipt["after"]["exit_code"] == 1
        )
        assert gh.prs == []
        assert (
            _git(["ls-remote", "--heads", "origin", lane.branch_name(FP)], work) == ""
        )
        assert _git(["branch", "--list", lane.branch_name(FP)], work) == ""

    def test_an_uninstalled_distribution_is_provisioned_once_then_pinned_to_what_arrived(
        self, tiny_repo
    ) -> None:
        installed = {"version": None}
        provisioned: list[str] = []

        def provision(distribution: str, root: Path) -> None:
            provisioned.append(distribution)
            installed["version"] = "1.4.0"

        _origin, work, base = tiny_repo
        cand = candidate()
        gh = FakeGitHub()
        receipt = lane.run_lane(
            issue_for(cand),
            repository=REPO,
            lease_comment=LANE_LEASE,
            root=work,
            base_sha=base,
            call=gh,
            git_call=lane.git,
            runner=fake_runner_factory({}),
            version_of=lambda name: installed["version"],
            provision=provision,
            discover=lambda root: {"candidates": [cand]},
        )
        assert provisioned == ["pytest-asyncio"]
        assert (
            receipt["outcome"] == "pr_opened" and receipt["edit"]["provisioned"] is True
        )
        assert receipt["edit"]["line"] == "pytest-asyncio==1.4.0"

    def test_without_a_provisioner_an_uninstalled_distribution_is_refused(
        self, tiny_repo
    ) -> None:
        receipt, gh, *_ = self.run(tiny_repo, version=None, provision=None)
        assert (
            receipt["outcome"] == "refused"
            and receipt["reason"] == "distribution_not_installed"
        )
        assert gh.prs == [] and receipt["changed_file_count"] == 0

    def test_a_condition_no_longer_present_is_proven_absent_then_done(
        self, tiny_repo
    ) -> None:
        receipt, gh, _origin, work, _base = self.run(
            tiny_repo, discover=lambda root: {"candidates": []}
        )
        # The fake validator fails while the line is absent, so absence alone
        # does not settle it: the command has to pass.
        assert (
            receipt["outcome"] == "validation_failed"
            and receipt["disposition"] == "blocked"
        )
        (work / "requirements-dev.txt").write_text(
            "pytest==9.1.1\npytest-asyncio==1.4.0\n"
        )
        receipt, gh, *_ = self.run(tiny_repo, discover=lambda root: {"candidates": []})
        assert (
            receipt["outcome"] == "condition_absent_validated"
            and receipt["disposition"] == "done"
        )
        assert gh.prs == []

    def test_a_candidate_from_another_source_is_refused_before_any_git(
        self, tiny_repo
    ) -> None:
        cand = candidate(source="failing-test")
        receipt, *_ = self.run(tiny_repo, cand=cand)
        assert (
            receipt["outcome"] == "refused"
            and receipt["reason"] == "unsupported_source"
        )

    def test_the_issue_and_the_candidate_must_name_the_same_command(
        self, tiny_repo
    ) -> None:
        _origin, work, base = tiny_repo
        cand = candidate()
        other = candidate(command="control-plane-tests")
        receipt = lane.run_lane(
            issue_for(other),
            repository=REPO,
            lease_comment=LANE_LEASE,
            root=work,
            base_sha=base,
            call=FakeGitHub(),
            git_call=lane.git,
            runner=fake_runner_factory({}),
            version_of=lambda name: "1.4.0",
            provision=None,
            discover=lambda root: {"candidates": [cand]},
        )
        assert receipt["reason"] == "issue_and_candidate_disagree_on_command"

    def test_a_base_that_already_declares_it_under_another_pin_is_refused(
        self, tiny_repo
    ) -> None:
        """The checkout lacks the line; ``base_sha`` carries it as ``>=``.

        Discovery ran on the checkout, so the candidate is real there. The
        edit lands on ``base_sha``, where the distribution is already declared
        under a floating pin: the lane must refuse, not append a second line.
        """
        _origin, work, base_a = tiny_repo
        (work / "requirements-dev.txt").write_text(
            "pytest==9.1.1\npytest-asyncio>=0.20\n"
        )
        _git(
            [
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.com",
                "commit",
                "-q",
                "-am",
                "declare loosely",
            ],
            work,
        )
        base_b = _git(["rev-parse", "HEAD"], work)
        _git(["push", "-q", "origin", "HEAD:main"], work)
        _git(["checkout", "-q", base_a], work)
        cand = candidate()
        gh = FakeGitHub()
        receipt = lane.run_lane(
            issue_for(cand),
            repository=REPO,
            lease_comment=LANE_LEASE,
            root=work,
            base_sha=base_b,
            call=gh,
            git_call=lane.git,
            runner=fake_runner_factory({}),
            version_of=lambda name: "1.4.0",
            provision=None,
            discover=lambda root: {"candidates": [cand]},
            worktree_root=work.parent,
        )
        assert receipt["outcome"] == "refused"
        assert receipt["reason"] == "already_declared"
        assert receipt["changed_file_count"] == 0 and gh.prs == []
        assert (
            _git(["ls-remote", "--heads", "origin", lane.branch_name(FP)], work) == ""
        )
        assert _git(["branch", "--list", lane.branch_name(FP)], work) == ""

    def test_a_stale_remote_branch_without_a_pr_fails_closed(self, tiny_repo) -> None:
        _origin, work, _base = tiny_repo
        _git(["push", "-q", "origin", f"HEAD:refs/heads/{lane.branch_name(FP)}"], work)
        receipt, gh, *_ = self.run(tiny_repo)
        assert (
            receipt["outcome"] == "unconfirmed"
            and receipt["reason"] == "branch_exists_without_pull_request"
        )
        assert gh.prs == []

    def test_the_only_push_is_one_fenced_refspec_even_without_a_hook(
        self, tiny_repo
    ) -> None:
        # tiny_repo has no pre-push hook: this is the lane's own fence alone.
        pushes: list[list[str]] = []

        def recording_git(args, cwd=None):
            if args and args[0] == "push":
                pushes.append(list(args))
            return lane.git(args, cwd)

        origin, work, base = tiny_repo
        cand = candidate()
        receipt = lane.run_lane(
            issue_for(cand),
            repository=REPO,
            lease_comment=LANE_LEASE,
            root=work,
            base_sha=base,
            call=FakeGitHub(),
            git_call=recording_git,
            runner=fake_runner_factory({}),
            version_of=lambda name: "1.4.0",
            provision=None,
            discover=lambda root: {"candidates": [cand]},
            worktree_root=work.parent,
        )
        assert receipt["outcome"] == "pr_opened"
        assert pushes == [
            ["push", "origin", f"{receipt['commit_sha']}:refs/heads/oc/discovered-{FP}"]
        ]
        heads = sorted(
            line.split()[1]
            for line in _git(["ls-remote", "--heads", "origin"], work).splitlines()
        )
        assert heads == ["refs/heads/main", f"refs/heads/oc/discovered-{FP}"]
        assert _git(["rev-parse", "refs/heads/main"], origin) == base

    def test_a_branch_outside_the_fence_is_refused_before_git_pushes(
        self, tiny_repo, monkeypatch
    ) -> None:
        origin, work, base = tiny_repo
        monkeypatch.setattr(
            lane, "branch_name", lambda fingerprint: "release-candidate"
        )
        with pytest.raises(lane.PushFenceViolation):
            self.run(tiny_repo)
        assert _git(["ls-remote", "--heads", "origin"], work).count("\n") == 0
        assert _git(["rev-parse", "refs/heads/main"], origin) == base

    def test_a_commit_outside_the_lease_write_set_is_never_pushed(
        self, tiny_repo
    ) -> None:
        _origin, work, _base = tiny_repo
        receipt, gh, *_ = self.run(tiny_repo, lease=lease_comment(["traits"]))
        assert receipt["outcome"] == "refused"
        assert receipt["reason"] == "write_set_exceeds_lease"
        assert receipt["changed_file_count"] == 0 and gh.prs == []
        assert receipt["edit"]["write_set"]["violations"][0]["missing_writes"] == [
            "repo-global"
        ]
        assert (
            _git(["ls-remote", "--heads", "origin", lane.branch_name(FP)], work) == ""
        )

    @pytest.mark.parametrize(
        "lease",
        [
            "",
            "no receipt here",
            "[OC-SWARM-V4] Dependency/resource lease claimed: none",
        ],
    )
    def test_a_pass_without_a_durable_lease_refuses_before_reading_the_tree(
        self, tiny_repo, lease
    ) -> None:
        _origin, work, base = tiny_repo
        with pytest.raises(ValueError):
            lane.run_lane(
                issue_for(candidate()),
                repository=REPO,
                lease_comment=lease,
                root=work,
                base_sha=base,
                call=lambda args, payload: pytest.fail(
                    "no GitHub call without a lease"
                ),
                discover=lambda root: pytest.fail(
                    "must refuse before reading the tree"
                ),
            )

    def test_the_pr_links_its_issue_for_write_set_verification(self, tiny_repo) -> None:
        receipt, gh, *_ = self.run(tiny_repo)
        assert receipt["outcome"] == "pr_opened"
        assert "\nOC-AUTO-ISSUE: #9000\n" in gh.prs[0]["body"]

    def test_the_pr_base_is_pinned_to_the_integration_branch(self, tiny_repo) -> None:
        _origin, work, base = tiny_repo
        with pytest.raises(ValueError, match="integration branch"):
            lane.run_lane(
                issue_for(candidate()),
                repository=REPO,
                lease_comment=LANE_LEASE,
                root=work,
                base_sha=base,
                integration_branch="main",
                call=FakeGitHub(),
                discover=lambda root: pytest.fail(
                    "must refuse before reading the tree"
                ),
            )


SHA = "a" * 40


class TestPushFence:
    def test_the_lane_branch_is_the_one_accepted_shape(self) -> None:
        dest = f"refs/heads/{lane.branch_name(FP)}"
        assert lane.fenced_push_args(SHA, dest) == ["push", "origin", f"{SHA}:{dest}"]

    @pytest.mark.parametrize(
        "destination",
        [
            "refs/heads/main",
            "refs/heads/oc-autonomous-integration",
            "main",
            f"oc/discovered-{FP}",  # unqualified: push.default could resolve it
            "refs/heads/oc/discovered-abc",
            f"refs/heads/oc/discovered-{FP.upper()}",
            f"refs/heads/oc/discovered-{FP}0",
            f"refs/heads/oc/discovered-{FP}/x",
            f"refs/tags/oc/discovered-{FP}",
            f"refs/heads/x/oc/discovered-{FP}",
            f"refs/heads/oc/discovered-{FP}\nrefs/heads/main",
            "",
        ],
    )
    def test_destinations_outside_the_fence_are_refused(self, destination) -> None:
        with pytest.raises(lane.PushFenceViolation):
            lane.fenced_push_args(SHA, destination)

    @pytest.mark.parametrize("source", ["HEAD", "main", "a" * 39, "", "A" * 40])
    def test_the_source_must_be_a_full_commit_id(self, source) -> None:
        with pytest.raises(lane.PushFenceViolation):
            lane.fenced_push_args(source, f"refs/heads/{lane.branch_name(FP)}")

    @pytest.mark.parametrize(
        "args",
        [
            ["push", "--force", "origin", f"{SHA}:refs/heads/oc/discovered-{FP}"],
            ["push", "-f", "origin", f"{SHA}:refs/heads/oc/discovered-{FP}"],
            ["push", "origin", f"+{SHA}:refs/heads/oc/discovered-{FP}"],
            ["push", "origin", f":refs/heads/oc/discovered-{FP}"],
            ["push", "--delete", "origin", f"refs/heads/oc/discovered-{FP}"],
            ["push", "origin", "--delete", f"refs/heads/oc/discovered-{FP}"],
            ["push", "origin", f"--force-with-lease={SHA}"],
            ["push", "--no-verify", "origin", f"{SHA}:refs/heads/oc/discovered-{FP}"],
            ["push", "--mirror", "origin"],
            ["push", "--all", "origin"],
            ["push", "origin"],
            ["push", "upstream", f"{SHA}:refs/heads/oc/discovered-{FP}"],
            [
                "push",
                "origin",
                f"{SHA}:refs/heads/oc/discovered-{FP}",
                f"{SHA}:refs/heads/main",
            ],
            ["push", "origin", f"{SHA}:refs/heads/oc/discovered-{FP}:x"],
        ],
    )
    def test_force_delete_options_and_extra_refspecs_are_refused(self, args) -> None:
        with pytest.raises(lane.PushFenceViolation):
            lane.assert_fenced_push(args)


class TestUndeclaredImportRemedy:
    """The starlette-shaped finding: declared where imported, proven by the import check."""

    @pytest.fixture()
    def app_repo(self, tiny_repo) -> tuple[Path, Path, str]:
        origin, work, _ = tiny_repo
        (work / "app").mkdir()
        (work / "app" / "__init__.py").write_text("")
        (work / "app" / "main.py").write_text("import starlette\n")
        (work / "app" / "routers").mkdir()
        (work / "app" / "routers" / "__init__.py").write_text("")
        (work / "app" / "routers" / "calyx_core.py").write_text(
            "ROUTER = 'calyx-core'\n"
        )
        _git(["add", "."], work)
        _git(
            [
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.com",
                "commit",
                "-q",
                "-m",
                "app",
            ],
            work,
        )
        return origin, work, _git(["rev-parse", "HEAD"], work)

    def test_discovery_binds_the_import_check_for_production_paths(self) -> None:
        assert discovery.import_validation_command(
            ["app/main.py", "app/university/learner_auth.py"]
        ) == ("production-runtime-imports")
        assert (
            discovery.import_validation_command(["runtime/brain_router.py"])
            == "production-runtime-imports"
        )

    def test_a_path_outside_the_production_trees_names_no_command(self) -> None:
        assert (
            discovery.import_validation_command(["app/main.py", "scripts/oc_x.py"])
            == ""
        )
        assert discovery.import_validation_command(["tests/test_x.py"]) == ""
        assert discovery.import_validation_command([]) == ""

    def test_the_real_repository_finding_is_bound(self, tmp_path: Path) -> None:
        cand = discovery.discover_undeclared_imports(
            _production_tree(tmp_path), provided_by={"starlette": ["starlette"]}
        )
        assert [c.validation_command for c in cand] == ["production-runtime-imports"]
        assert cand[0].remedy["requirements_file"] == "requirements.txt"

    def test_a_finding_outside_the_trees_is_refused_by_the_lane(
        self, tmp_path: Path
    ) -> None:
        cand = candidate(
            source="undeclared-import", distribution="starlette", command=""
        )
        cand["evidence"] = [
            {
                "kind": "undeclared-direct-import",
                "where": "scripts/oc_x.py",
                "detail": "d",
            }
        ]
        with pytest.raises(lane.LaneRefusal, match="no_validation_command"):
            lane.derive_edit(cand, tmp_path, version_of=lambda name: "0.46.2")

    def test_the_lane_declares_starlette_and_the_import_check_settles_it(
        self, app_repo
    ) -> None:
        pytest.importorskip("starlette")
        from importlib.metadata import version

        _origin, work, base = app_repo
        report = discovery.discover(work)
        found = [c for c in report["candidates"] if c["source"] == "undeclared-import"]
        assert [c["remedy"]["distribution"] for c in found] == ["starlette"]
        cand = found[0]
        assert cand["validation_command"] == "production-runtime-imports"

        def runner(argv, cwd, timeout):
            argv = [
                sys.executable if argv[0] in ("python3", "python") else argv[0],
                *argv[1:],
            ]
            return subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )

        gh = FakeGitHub()
        receipt = lane.run_lane(
            issue_for(cand),
            repository=REPO,
            lease_comment=LANE_LEASE,
            root=work,
            base_sha=base,
            call=gh,
            git_call=lane.git,
            runner=runner,
            version_of=lambda name: version(name),
            provision=None,
            worktree_root=work.parent,
        )
        assert receipt["outcome"] == "pr_opened", receipt
        assert receipt["edit"] == {
            "path": "requirements.txt",
            "line": f"starlette=={version('starlette')}",
            "distribution": "starlette",
            "version": version("starlette"),
            "provisioned": False,
        }
        # The import check passes on both sides; the declaration is what moved.
        assert receipt["before"]["passed"] and receipt["after"]["passed"]
        assert (
            receipt["before"]["pytest_shaped"] is False
            and receipt["before"]["conclusive"] is True
        )
        assert (
            receipt["before"]["declared"] is False
            and receipt["after"]["declared"] is True
        )
        assert (
            "declared in any requirements file: before False, after True"
            in gh.prs[0]["body"]
        )
        assert "+starlette==" in gh.prs[0]["body"]

    def test_an_edit_that_does_not_declare_is_not_a_pass(self) -> None:
        run = {
            "conclusive": True,
            "passed": True,
            "failing_node_ids": [],
            "pytest_shaped": False,
        }
        ok, why = lane.judge({**run, "declared": False}, {**run, "declared": False})
        assert (
            ok
        )  # judge alone is about the command; the lane adds the declaration check
        assert "passed" in why


def _production_tree(tmp_path: Path) -> Path:
    (tmp_path / "requirements.txt").write_text("fastapi<0.116\n")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("import starlette\n")
    return tmp_path


# -- End to end on this repository: the real gap, the real command -------------


@pytest.mark.skipif(
    os.environ.get("OC_EDIT_LANE_E2E") != "1",
    reason="set OC_EDIT_LANE_E2E=1: clones this repository and runs calyx-async-acceptance twice",
)
def test_the_lane_repairs_the_real_pytest_asyncio_gap(tmp_path: Path) -> None:
    """Re-create #1592 in a throwaway clone and let the lane close it.

    The clone shares this repository's objects. ``requirements-dev.txt`` loses
    its pytest-asyncio line and is committed as the base; discovery finds the
    gap with the live fingerprint; the lane runs ``calyx-async-acceptance``
    with the plugin disabled (``-p no:asyncio``, which is what "not installed"
    looks like to pytest) for the before run, "provisions" by enabling it, pins
    the version this interpreter has, runs again, pushes to a local bare
    remote, and files a PR through a fake ``gh``.
    """
    pytest_asyncio = pytest.importorskip("pytest_asyncio")
    origin = tmp_path / "origin.git"
    _git(["clone", "-q", "--bare", "--shared", str(ROOT), str(origin)], tmp_path)
    work = tmp_path / "work"
    _git(["clone", "-q", "--shared", str(origin), str(work)], tmp_path)
    requirements = work / "requirements-dev.txt"
    kept = [
        line
        for line in requirements.read_text().splitlines()
        if not line.startswith("pytest-asyncio")
    ]
    requirements.write_text("\n".join(kept) + "\n")
    _git(["add", "requirements-dev.txt"], work)
    _git(
        [
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-q",
            "-m",
            "re-create the gap",
        ],
        work,
    )
    base = _git(["rev-parse", "HEAD"], work)

    report = discovery.discover(work)
    gaps = [c for c in report["candidates"] if c["source"] == "dependency-gap"]
    assert [c["fingerprint"] for c in gaps] == [FP]
    assert gaps[0]["validation_command"] == "calyx-async-acceptance"

    state = {"provisioned": False}

    def runner(argv, cwd, timeout):
        argv = [
            sys.executable if argv[0] in ("python3", "python") else argv[0],
            *argv[1:],
        ]
        if not state["provisioned"]:
            argv += ["-p", "no:asyncio"]
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.upper().endswith(("_TOKEN", "_KEY"))
        }
        return subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )

    def provision(distribution: str, root: Path) -> None:
        state["provisioned"] = True

    def version_of(name: str) -> str | None:
        return pytest_asyncio.__version__ if state["provisioned"] else None

    gh = FakeGitHub()
    receipt = lane.run_lane(
        issue_for(gaps[0]),
        repository=REPO,
        lease_comment=LANE_LEASE,
        root=work,
        base_sha=base,
        call=gh,
        git_call=lane.git,
        runner=runner,
        version_of=version_of,
        provision=provision,
        worktree_root=tmp_path,
    )
    assert receipt["outcome"] == "pr_opened", receipt
    assert receipt["edit"]["line"] == f"pytest-asyncio=={pytest_asyncio.__version__}"
    assert len(receipt["before"]["failing_node_ids"]) == 26
    assert receipt["after"]["failing_node_ids"] == [] and receipt["after"]["passed"]
    assert receipt["changed_file_count"] == 1
    assert (
        _git(["rev-parse", f"refs/heads/{receipt['branch']}"], origin)
        == receipt["commit_sha"]
    )
    assert (
        "26 failing node id(s)" in gh.prs[0]["body"]
        and "0 failing node id(s)" in gh.prs[0]["body"]
    )
    again = lane.run_lane(
        issue_for(gaps[0]),
        repository=REPO,
        lease_comment=LANE_LEASE,
        root=work,
        base_sha=base,
        call=gh,
        git_call=lane.git,
        runner=runner,
        version_of=version_of,
        provision=provision,
    )
    assert again["outcome"] == "already_open" and len(gh.prs) == 1
