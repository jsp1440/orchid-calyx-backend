"""What the factory may file against itself, and what it must refuse to invent.

A discoverer's failure mode is not missing work. It is confidently filing work
that does not exist, and a queue full of invented tasks costs more than an empty
one. So most of these tests are about refusals.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import oc_work_discovery as discovery
from scripts.oc_product_lanes import LANES_BY_KEY, lane_for_path, rank_of

ASYNC_TEST = """
import pytest

@pytest.mark.asyncio
async def test_one():
    assert True

@pytest.mark.asyncio
async def test_two():
    assert True
"""


def repo(tmp_path: Path, *, requirements: str = "pytest==9.1.1\n", tests: dict[str, str] | None = None) -> Path:
    (tmp_path / "requirements-dev.txt").write_text(requirements, encoding="utf-8")
    directory = tmp_path / "tests"
    directory.mkdir(exist_ok=True)
    for name, body in (tests or {}).items():
        (directory / name).write_text(body, encoding="utf-8")
    return tmp_path


class TestDependencyGaps:
    def test_a_marker_no_requirements_file_declares_is_reported(self, tmp_path: Path) -> None:
        root = repo(tmp_path, tests={"test_calyx_brain_thing.py": ASYNC_TEST})
        candidates = discovery.discover_dependency_gaps(root)
        assert len(candidates) == 1
        assert "pytest-asyncio" in candidates[0].title
        assert candidates[0].lane is LANES_BY_KEY["calyx"]

    def test_one_file_using_the_marker_eight_times_is_one_file(self, tmp_path: Path) -> None:
        """The first version of this module counted occurrences and said 26 of 8."""
        root = repo(tmp_path, tests={"test_calyx_brain_thing.py": ASYNC_TEST * 4})
        candidate = discovery.discover_dependency_gaps(root)[0]
        assert len(candidate.evidence) == 1
        assert "1 test file(s)" in candidate.title

    def test_a_declared_distribution_is_not_a_gap(self, tmp_path: Path) -> None:
        root = repo(
            tmp_path,
            requirements="pytest==9.1.1\npytest-asyncio==1.4.0\n",
            tests={"test_calyx_brain_thing.py": ASYNC_TEST},
        )
        assert discovery.discover_dependency_gaps(root) == []

    def test_declaration_in_any_requirements_file_counts(self, tmp_path: Path) -> None:
        repo(tmp_path, tests={"test_calyx_brain_thing.py": ASYNC_TEST})
        (tmp_path / "requirements.txt").write_text("pytest-asyncio>=1,<2\n", encoding="utf-8")
        assert discovery.discover_dependency_gaps(tmp_path) == []

    def test_extras_and_pins_do_not_hide_a_declaration(self, tmp_path: Path) -> None:
        root = repo(
            tmp_path,
            requirements="pytest_asyncio[extra]==1.4.0 ; python_version>='3.9'\n",
            tests={"test_calyx_brain_thing.py": ASYNC_TEST},
        )
        assert discovery.discover_dependency_gaps(root) == []

    def test_a_marker_this_repository_registers_is_its_own_vocabulary(self, tmp_path: Path) -> None:
        root = repo(tmp_path, tests={"test_calyx_brain_thing.py": ASYNC_TEST})
        (root / "pytest.ini").write_text(
            "[pytest]\nmarkers =\n    asyncio: our own marker\n", encoding="utf-8"
        )
        assert discovery.discover_dependency_gaps(root) == []

    def test_an_unlisted_marker_produces_nothing(self, tmp_path: Path) -> None:
        """"A plugin is probably named after its marker" is the guess this refuses."""
        root = repo(
            tmp_path,
            tests={"test_calyx_brain_thing.py": "import pytest\n@pytest.mark.slow\ndef test_x(): pass\n"},
        )
        assert discovery.discover_dependency_gaps(root) == []

    def test_the_gap_takes_the_rank_of_its_most_important_affected_lane(self, tmp_path: Path) -> None:
        root = repo(
            tmp_path,
            tests={
                "test_vision_thing.py": ASYNC_TEST,
                "test_calyx_brain_thing.py": ASYNC_TEST,
            },
        )
        candidate = discovery.discover_dependency_gaps(root)[0]
        assert candidate.lane is LANES_BY_KEY["calyx"]
        assert candidate.priority_label == "oc-p1"

    def test_the_fingerprint_is_the_condition_not_the_run(self, tmp_path: Path) -> None:
        root = repo(tmp_path, tests={"test_calyx_brain_thing.py": ASYNC_TEST})
        first = discovery.discover_dependency_gaps(root)[0].fingerprint
        second = discovery.discover_dependency_gaps(root)[0].fingerprint
        assert first == second
        (root / "tests" / "test_calyx_other.py").write_text(ASYNC_TEST, encoding="utf-8")
        assert discovery.discover_dependency_gaps(root)[0].fingerprint != first


class TestFailingTests:
    REPORT = (
        "FAILED tests/test_calyx_brain_x.py::test_a - AssertionError: boom\n"
        "FAILED tests/test_calyx_brain_x.py::test_b\n"
        "ERROR tests/test_atlas_y.py::test_c\n"
        "4 failed, 10 passed in 1.00s\n"
    )

    def test_failures_are_grouped_into_one_task_per_file(self, tmp_path: Path) -> None:
        candidates = discovery.discover_failing_tests(self.REPORT, tmp_path)
        assert [candidate.lane.key for candidate in candidates] == ["calyx", "atlas"] or \
               sorted(candidate.lane.key for candidate in candidates) == ["atlas", "calyx"]
        assert len(candidates) == 2

    def test_every_node_id_travels_as_evidence(self, tmp_path: Path) -> None:
        calyx = next(c for c in discovery.discover_failing_tests(self.REPORT, tmp_path)
                     if c.lane.key == "calyx")
        assert {item.where for item in calyx.evidence} == {
            "tests/test_calyx_brain_x.py::test_a",
            "tests/test_calyx_brain_x.py::test_b",
        }

    def test_a_report_with_no_summary_line_is_refused(self, tmp_path: Path) -> None:
        """An empty failure set from a run that collected nothing is not a green run.

        AGENT-OPERATING-MEMORY records a comparison that reported "zero new
        failures" across two runs that never executed a test.
        """
        with pytest.raises(ValueError, match="no summary line"):
            discovery.discover_failing_tests("some unrelated output\n", tmp_path)

    def test_an_empty_report_is_simply_no_candidates(self, tmp_path: Path) -> None:
        assert discovery.discover_failing_tests("", tmp_path) == []

    def test_fixing_some_of_the_failures_changes_the_condition(self, tmp_path: Path) -> None:
        full = discovery.discover_failing_tests(self.REPORT, tmp_path)
        partial = discovery.discover_failing_tests(
            "FAILED tests/test_calyx_brain_x.py::test_a\n1 failed in 1.00s\n", tmp_path
        )
        assert full[0].fingerprint != partial[0].fingerprint


class TestItRefusesToGuess:
    def test_an_unplaced_path_keeps_no_lane(self) -> None:
        assert lane_for_path("tests/test_something_nobody_mapped.py") is None
        assert lane_for_path("app/a_module_nobody_mapped/thing.py") is None

    def test_an_unplaced_candidate_sorts_last(self) -> None:
        assert rank_of(None) > max(lane.rank for lane in LANES_BY_KEY.values())

    def test_unplaced_findings_become_one_bounded_analysis_task(self, tmp_path: Path) -> None:
        report = (
            "FAILED tests/test_unmapped_alpha.py::test_a\n"
            "FAILED tests/test_unmapped_beta.py::test_b\n"
            "2 failed in 1.00s\n"
        )
        result = discovery.discover(tmp_path, pytest_report=report)
        questions = [c for c in result["candidates"] if c["source"] == "binding-gap"]
        assert len(questions) == 1, "one question about the table, not one per finding"
        assert questions[0]["lane"] is None
        assert questions[0]["analysis_only"] is True
        assert "oc-lane:" not in " ".join(questions[0]["labels"])

    def test_no_analysis_task_when_everything_placed(self, tmp_path: Path) -> None:
        report = "FAILED tests/test_calyx_brain_x.py::test_a\n1 failed in 1.00s\n"
        result = discovery.discover(tmp_path, pytest_report=report)
        assert [c for c in result["candidates"] if c["source"] == "binding-gap"] == []


class TestOneDefectIsOneTask:
    def test_a_dependency_gap_absorbs_the_failures_it_explains(self, tmp_path: Path) -> None:
        """Two lanes on one defect, and the second reports a phantom failure."""
        root = repo(tmp_path, tests={"test_calyx_brain_x.py": ASYNC_TEST})
        report = (
            "FAILED tests/test_calyx_brain_x.py::test_one - async def functions are not "
            "natively supported\n1 failed in 1.00s\n"
        )
        result = discovery.discover(root, pytest_report=report)
        sources = [c["source"] for c in result["candidates"]]
        assert sources == ["dependency-gap"]
        assert result["suppressed_by_dependency_gap"]

    def test_an_unrelated_failure_survives_the_suppression(self, tmp_path: Path) -> None:
        root = repo(tmp_path, tests={"test_calyx_brain_x.py": ASYNC_TEST})
        report = (
            "FAILED tests/test_calyx_brain_x.py::test_one\n"
            "FAILED tests/test_atlas_y.py::test_c\n2 failed in 1.00s\n"
        )
        result = discovery.discover(root, pytest_report=report)
        assert sorted(c["source"] for c in result["candidates"]) == [
            "dependency-gap",
            "failing-test",
        ]


class TestReportShape:
    def test_candidates_are_ranked_highest_lane_first(self, tmp_path: Path) -> None:
        report = (
            "FAILED tests/test_atlas_y.py::test_c\n"
            "FAILED tests/test_calyx_brain_x.py::test_a\n2 failed in 1.00s\n"
        )
        result = discovery.discover(tmp_path, pytest_report=report)
        ranks = [c["rank"] for c in result["candidates"]]
        assert ranks == sorted(ranks)
        assert result["candidates"][0]["lane"] == "calyx"

    def test_the_report_states_it_mutated_nothing(self, tmp_path: Path) -> None:
        result = discovery.discover(tmp_path)
        assert result["safety"] == {
            "provider_calls": False,
            "github_mutation": False,
            "repository_writes": False,
            "invented_work": False,
        }

    def test_this_repository_is_covered_by_the_lane_table(self) -> None:
        """A live check, not a fixture: the table must place this repo's own tests."""
        root = Path(__file__).resolve().parents[1]
        gaps = discovery.discover_dependency_gaps(root)
        for candidate in gaps:
            assert candidate.lane is not None, candidate.title


class TestExecutableCoupling:
    """A filed task is only executable when a real command covers its evidence."""

    def test_the_covering_command_is_the_smallest_one_that_covers_everything(self) -> None:
        assert discovery.covering_validation_command(
            ["tests/test_oc_blocked_reconcile.py"]
        ) == "control-plane-tests"

    def test_partial_coverage_names_no_command(self) -> None:
        """Settling on a run over some of the affected files is a false pass."""
        assert discovery.covering_validation_command(
            ["tests/test_oc_blocked_reconcile.py", "tests/test_provider_reservoir.py"]
        ) == ""

    def test_an_uncovered_path_names_no_command(self) -> None:
        assert discovery.covering_validation_command(["tests/test_nothing_runs_this.py"]) == ""

    def test_no_paths_names_no_command(self) -> None:
        assert discovery.covering_validation_command([]) == ""

    def test_this_repositorys_async_gap_resolves_to_a_real_command(self) -> None:
        from scripts.oc_validation_commands import VALIDATION_COMMANDS

        root = Path(__file__).resolve().parents[1]
        gaps = discovery.discover_dependency_gaps(root)
        if not gaps:
            pytest.skip("the gap this covers has been closed; nothing to bind")
        command = gaps[0].validation_command
        assert command in VALIDATION_COMMANDS
        covered = set(VALIDATION_COMMANDS[command].argv)
        assert {item.where for item in gaps[0].evidence} <= covered


class TestMarkersComeFromCodeNotText:
    def test_a_marker_inside_a_string_is_not_a_marker(self) -> None:
        """This module's own test file holds the decorator inside a fixture."""
        source = 'FIXTURE = """\n@pytest.mark.asyncio\nasync def test_x(): ...\n"""\n'
        assert discovery.markers_used(source) == set()

    def test_a_decorated_function_is(self) -> None:
        assert discovery.markers_used(
            "import pytest\n@pytest.mark.asyncio\nasync def test_x(): ...\n"
        ) == {"asyncio"}

    def test_a_parametrised_marker_is_read_by_name(self) -> None:
        assert discovery.markers_used(
            "import pytest\n@pytest.mark.asyncio(loop_scope='session')\nasync def test_x(): ...\n"
        ) == {"asyncio"}

    def test_a_module_level_pytestmark_applies(self) -> None:
        assert discovery.markers_used("import pytest\npytestmark = pytest.mark.asyncio\n") == {"asyncio"}
        assert discovery.markers_used("import pytest\npytestmark = [pytest.mark.asyncio]\n") == {"asyncio"}

    def test_a_file_that_does_not_parse_reports_nothing(self) -> None:
        """A syntax error is a different defect, and naming the wrong one is worse."""
        assert discovery.markers_used("def broken(:\n") == set()

    def test_this_modules_own_test_file_is_not_reported_as_affected(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for candidate in discovery.discover_dependency_gaps(root):
            assert "test_oc_work_discovery.py" not in {i.where for i in candidate.evidence}
