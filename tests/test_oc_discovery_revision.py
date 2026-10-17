"""Discovery and settlement judge one revision, and every receipt names it.

#1977 flapped between done and requeued: the controller's ``issues`` and
``pull_request`` runs discovered on ``main``'s side, where
``app/field_observation/drive_archive.py`` existed, while the edit lane settled
on integration heads 4a35c540 and fe8604ef, which did not contain it. Each
revision was right about itself; reading them as one history was the defect.

These tests pin the three parts of the fix:

* the discovery report records the commit it read, observed from the tree;
* the materializer refuses a report about any revision but the one settlement
  uses, so a condition present on ``main`` and absent on integration does not
  flap, and the issue, clearance and recurrence receipts carry the revision;
* the controller discovers only on the integration head and leaves discovered
  issues unleased on any other run.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import test_oc_work_materialize as harness

from scripts import oc_swarm_controller as swarm
from scripts import oc_work_discovery as discovery
from scripts import oc_work_materialize as materialize

yaml = pytest.importorskip("yaml")

REPO = harness.REPO
WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "orchid-swarm-controller.yml"
)

#: Provider map injected in place of the environment's: ``fakemod`` is provided
#: by ``fakedist``, which no requirements file in the fixture declares.
PROVIDES = {"fakemod": ["fakedist"], "yaml": ["PyYAML"]}

LAZY_IMPORT = """
def archive():
    import fakemod  # lazy, like drive_archive.py's httplib2 import

    return fakemod
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def two_revisions(tmp_path: Path) -> dict[str, object]:
    """An integration head without the lazy import and a main head with it."""
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    git(root, "init", "-q", "-b", "oc-autonomous-integration")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "fixture")
    (root / "requirements.txt").write_text("PyYAML==6.0.2\n", encoding="utf-8")
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "integration")
    integration = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-q", "-b", "main")
    # A lane-bound path, so the finding is one candidate and not also a
    # binding question.
    (root / "app" / "lexicon").mkdir()
    (root / "app" / "lexicon" / "drive_archive.py").write_text(
        LAZY_IMPORT, encoding="utf-8"
    )
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "main adds the lazy import")
    main = git(root, "rev-parse", "HEAD")
    return {"root": root, "integration": integration, "main": main}


def discover_at(root: Path, revision: str, monkeypatch: pytest.MonkeyPatch) -> dict:
    git(root, "checkout", "-q", "--detach", revision)
    monkeypatch.setattr(discovery, "packages_distributions", lambda: PROVIDES)
    return json.loads(json.dumps(discovery.discover(root)))


# -- the report records the revision it read ---------------------------------


class TestTheReportNamesItsRevision:
    def test_a_clean_tree_records_its_head(self, two_revisions, monkeypatch) -> None:
        root, integration = two_revisions["root"], two_revisions["integration"]
        report = discover_at(root, integration, monkeypatch)
        assert report["revision"] == {"sha": integration, "state": "clean"}

    def test_each_revision_reports_itself_and_its_own_findings(
        self, two_revisions, monkeypatch
    ) -> None:
        root = two_revisions["root"]
        on_main = discover_at(root, two_revisions["main"], monkeypatch)
        on_integration = discover_at(root, two_revisions["integration"], monkeypatch)
        assert on_main["revision"]["sha"] == two_revisions["main"]
        assert [c["source"] for c in on_main["candidates"]] == ["undeclared-import"]
        assert on_integration["revision"]["sha"] == two_revisions["integration"]
        assert on_integration["candidates"] == []

    def test_a_dirty_tree_lists_what_differs(self, two_revisions, monkeypatch) -> None:
        root = two_revisions["root"]
        git(root, "checkout", "-q", "--detach", two_revisions["integration"])
        (root / "calyx_runtime_journal.jsonl").write_text("{}\n", encoding="utf-8")
        revision = discovery.read_revision(root)
        assert revision["sha"] == two_revisions["integration"]
        assert revision["state"] == "dirty"
        assert revision["changed_paths"] == ["calyx_runtime_journal.jsonl"]
        assert revision["changed_path_count"] == 1

    def test_a_directory_that_is_not_a_work_tree_root_records_nothing(
        self, two_revisions, tmp_path
    ) -> None:
        assert discovery.read_revision(two_revisions["root"] / "app") == {
            "sha": None,
            "state": "unavailable",
        }
        plain = tmp_path / "plain"
        plain.mkdir()
        assert discovery.read_revision(plain) == {"sha": None, "state": "unavailable"}

    def test_git_failing_is_unavailable_not_an_exception(self, tmp_path) -> None:
        def broken(*_args, **_kwargs):
            raise OSError("git is not installed")

        assert discovery.read_revision(tmp_path, run=broken) == {
            "sha": None,
            "state": "unavailable",
        }

    def test_the_cli_refuses_a_tree_at_another_revision(
        self, two_revisions, monkeypatch, capsys
    ) -> None:
        root = two_revisions["root"]
        git(root, "checkout", "-q", "--detach", two_revisions["main"])
        monkeypatch.setattr(discovery, "packages_distributions", lambda: PROVIDES)
        assert (
            discovery.main(
                ["--root", str(root), "--expect-revision", two_revisions["integration"]]
            )
            == 2
        )
        # The report is still printed, so the run log shows what was read.
        assert (
            json.loads(capsys.readouterr().out)["revision"]["sha"]
            == two_revisions["main"]
        )
        assert (
            discovery.main(
                ["--root", str(root), "--expect-revision", two_revisions["main"]]
            )
            == 0
        )

    def test_the_cli_refuses_an_abbreviated_expected_revision(
        self, two_revisions
    ) -> None:
        with pytest.raises(SystemExit) as raised:
            discovery.main(
                [
                    "--root",
                    str(two_revisions["root"]),
                    "--expect-revision",
                    two_revisions["main"][:12],
                ]
            )
        assert raised.value.code == 2


# -- the materializer: no flap, and the revision on every receipt -------------


def bodies(transport: harness.FakeGitHub, kind: str) -> list[str]:
    return [call[call.index("--body") + 1] for call in transport.writes(kind)]


def run(transport: harness.FakeGitHub, report: dict, *, expected: str | None) -> dict:
    index = materialize.scan_discovered_issues(REPO, call=transport)
    planned = materialize.plan(
        report,
        index,
        expected_revision=expected,
        search=lambda fp: materialize.search_fingerprint(REPO, fp, call=transport),
    )
    return materialize.apply_plan(planned, REPO, dry_run=False, call=transport)


class TestNoFlapAcrossRevisions:
    def resolved(
        self, two_revisions, monkeypatch
    ) -> tuple[harness.FakeGitHub, dict, dict]:
        """File on main (as #1977 was), then settle it done."""
        root = two_revisions["root"]
        on_main = discover_at(root, two_revisions["main"], monkeypatch)
        on_integration = discover_at(root, two_revisions["integration"], monkeypatch)
        transport = harness.FakeGitHub()
        filed = run(transport, on_main, expected=None)
        assert filed["created_count"] == 1
        harness.resolve(transport, 1)
        return transport, on_main, on_integration

    def test_without_a_pinned_revision_the_two_revisions_flap(
        self, two_revisions, monkeypatch
    ) -> None:
        """The defect, reproduced: absent on integration, present on main, requeued."""
        transport, on_main, on_integration = self.resolved(two_revisions, monkeypatch)
        assert run(transport, on_integration, expected=None)["cleared_count"] == 1
        assert run(transport, on_main, expected=None)["requeued_count"] == 1

    def test_present_on_main_absent_on_integration_does_not_flap(
        self, two_revisions, monkeypatch
    ) -> None:
        transport, on_main, on_integration = self.resolved(two_revisions, monkeypatch)
        integration = two_revisions["integration"]
        for _ in range(3):  # alternate the two revisions, as the triggers did
            run(transport, on_integration, expected=integration)
            refused = run(transport, on_main, expected=integration)
            assert refused["planned_count"] == 0
            assert refused["requeued_count"] == 0
            assert refused["errors"] == [
                {
                    "reason": "discovery_revision_mismatch",
                    "expected_revision": integration,
                    "report_revision": two_revisions["main"],
                }
            ]
        issue = transport.get(1)
        assert issue["state"] == "CLOSED"
        assert "oc-done" in issue["labels"]
        assert transport.writes("reopen") == []
        fingerprint = on_main["candidates"][0]["fingerprint"]
        assert bodies(transport, "comment") == [
            (
                f"{materialize.CLEARANCE_MARKER}: {fingerprint}\n\n"
                "Work discovery evaluated this condition's source and did not find it.\n\n"
                f"- Absent at discovery revision: `{integration}`"
            )
        ]

    def test_a_report_naming_no_revision_is_refused_when_one_is_expected(
        self, two_revisions
    ) -> None:
        planned = materialize.plan(
            harness.report(harness.candidate()),
            {},
            expected_revision=two_revisions["integration"],
        )
        assert planned["actions"] == []
        assert planned["errors"][0]["report_revision"] is None

    def test_a_dirty_report_at_the_expected_head_is_accepted(self) -> None:
        sha = "b" * 40
        report = {
            **harness.report(harness.candidate()),
            "revision": {
                "sha": sha,
                "state": "dirty",
                "changed_paths": ["x"],
                "changed_path_count": 1,
            },
        }
        planned = materialize.plan(report, {}, expected_revision=sha)
        assert planned["action_count"] == 1
        assert planned["discovery_revision"] == sha

    def test_an_abbreviated_expected_revision_is_refused(self) -> None:
        with pytest.raises(ValueError, match="40-hex"):
            materialize.plan(harness.report(), {}, expected_revision="b" * 12)
        with pytest.raises(SystemExit):
            materialize.main(
                [
                    "--repository",
                    REPO,
                    "--report",
                    "unused.json",
                    "--expected-revision",
                    "b" * 12,
                ]
            )


class TestTheRevisionIsOnEveryReceipt:
    def test_filing_clearing_and_recurrence_each_name_their_revision(self) -> None:
        first, second, third = "1" * 40, "2" * 40, "3" * 40

        def at(sha: str, *candidates: dict) -> dict:
            return {
                **harness.report(*candidates),
                "revision": {"sha": sha, "state": "clean"},
            }

        transport = harness.FakeGitHub()
        filed = run(transport, at(first, harness.candidate()), expected=first)
        assert filed["results"][0]["revision"] == first
        assert f"- Discovery revision: `{first}`" in transport.get(1)["body"]
        harness.resolve(transport, 1)

        cleared = run(transport, at(second), expected=second)
        assert cleared["results"][0]["revision"] == second
        assert cleared["discovery_revision"] == second
        recurred = run(transport, at(third, harness.candidate()), expected=third)
        assert recurred["results"][0] == {
            "fingerprint": harness.FP,
            "outcome": "requeued",
            "issue_number": 1,
            "revision": third,
        }

        clearance, recurrence = bodies(transport, "comment")
        assert f"- Absent at discovery revision: `{second}`" in clearance
        assert recurrence.startswith(f"{materialize.RECURRENCE_MARKER}: {harness.FP}")
        assert f"- Present at discovery revision: `{third}`" in recurrence

    def test_a_report_without_a_revision_says_so_rather_than_guessing(self) -> None:
        transport = harness.FakeGitHub()
        run(transport, harness.report(harness.candidate()), expected=None)
        assert "Discovery revision" not in transport.get(1)["body"]
        harness.resolve(transport, 1)
        run(transport, harness.report(), expected=None)
        run(transport, harness.report(harness.candidate()), expected=None)
        clearance, recurrence = bodies(transport, "comment")
        assert "unrecorded (the report named no revision)" in clearance
        assert "unrecorded (the report named no revision)" in recurrence


# -- the controller: discover and settle on the integration head only ---------


def _plan_job() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"]["plan"]


def _plan_step(name: str) -> dict:
    return next(step for step in _plan_job()["steps"] if step.get("name") == name)


class TestControllerWiring:
    def test_discovery_runs_only_on_the_integration_head_and_pins_it(self) -> None:
        step = _plan_step("Discover product work from repository evidence")
        assert (
            step["if"]
            == "steps.controller_revision.outputs.canonical_integration == 'true'"
        )
        assert (
            step["env"]["DISCOVERY_REVISION"]
            == "${{ steps.controller_revision.outputs.sha }}"
        )
        assert '--expect-revision "$DISCOVERY_REVISION"' in step["run"]
        assert "revision" in step["run"].split("jq", 1)[1]

    def test_materialization_refuses_any_other_revision(self) -> None:
        step = _plan_step("File discovered work into the canonical queue")
        assert step["if"] == "steps.discovery.outcome == 'success'"
        assert (
            step["env"]["DISCOVERY_REVISION"]
            == "${{ steps.controller_revision.outputs.sha }}"
        )
        assert '--expected-revision "$DISCOVERY_REVISION"' in step["run"]

    def test_the_canonical_flag_still_compares_the_checkout_with_the_integration_head(
        self,
    ) -> None:
        run_text = _plan_step("Record canonical controller revision")["run"]
        assert 'if [[ "$controller_sha" == "$integration_sha" ]]; then' in run_text
        assert 'git fetch origin "$INTEGRATION_BRANCH" --depth=1' in run_text

    def test_off_integration_runs_defer_discovered_issues(self) -> None:
        run_text = _plan_step("Plan dependency-aware resource wave")["run"]
        assert "provider_args+=(--defer-edit-mode --defer-discovered)" in run_text


def _discovered_snapshot() -> dict:
    fingerprinted = (
        "OC-SWARM-PROVIDER-FREE: validate\nOC-SWARM-VALIDATE: ruff-check\n\n"
        "OC-DISCOVERY-FINGERPRINT: 578850d1e54d328d"
    )
    return {
        "issues": [
            {
                "number": 1977,
                "state": "OPEN",
                "labels": ["oc-queued", "oc-discovered"],
                "body": fingerprinted,
            },
            {
                "number": 1978,
                "state": "OPEN",
                "labels": ["oc-discovered"],
                "body": fingerprinted,
            },
            {
                "number": 1979,
                "state": "OPEN",
                "labels": ["oc-queued"],
                "body": "OC-SWARM-PROVIDER-FREE: validate\nOC-SWARM-VALIDATE: ruff-check",
            },
            {
                "number": 1980,
                "state": "OPEN",
                "labels": ["oc-queued"],
                "body": "mentions OC-DISCOVERY-FINGERPRINT: 578850d1e54d328d inline",
            },
        ]
    }


class TestPlannerDeferral:
    def test_only_queued_fingerprinted_issues_are_deferred(self) -> None:
        assert swarm.discovered_deferred_numbers(_discovered_snapshot()) == [1977]
