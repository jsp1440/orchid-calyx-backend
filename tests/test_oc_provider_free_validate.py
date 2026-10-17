"""The deterministic lane's second executor, and what it may claim.

``reconcile`` settles an issue from a disposition the issue declares, which
means a completed provider-free cycle could carry no evidence about the
revision at all. ``validate`` runs named commands and settles from their exit
codes. These tests pin the asymmetry that makes that safe: a pass must be
earned, a failure cannot be declared away, and an issue body cannot become a
command line.
"""

from __future__ import annotations

import subprocess

import pytest

from scripts import oc_provider_free_validate as executor
from scripts import oc_validation_commands as registry

#: Top-level packages that live in this repository. A ``-m`` target outside this set
#: (``pytest``, ``compileall``) is an installed or standard-library module, not ours.
PROJECT_PACKAGES = frozenset({"scripts", "app", "runtime", "tests"})


def missing_registry_targets(commands, root) -> list[str]:
    """Registry arguments that name a file, directory or module that does not exist.

    A part after ``-m`` is a dotted module name, not a path: ``scripts.oc_brain_pulse``
    is checked as ``scripts/oc_brain_pulse.py`` (or a package), never as a file with a
    dot in its name. Modules outside this repository (``pytest``) are not checked. Every
    other part keeps the original path rule.
    """
    missing: list[str] = []
    for command in commands:
        argv = tuple(command.argv)
        for index, part in enumerate(argv):
            if (
                index
                and argv[index - 1] == "-m"
                and part.split(".")[0] in PROJECT_PACKAGES
            ):
                module = root.joinpath(*part.split("."))
                if not (
                    module.with_suffix(".py").exists()
                    or (module / "__init__.py").exists()
                ):
                    missing.append(f"{command.command_id} names module {part}")
            elif part.startswith(("tests/", "scripts")):
                if not (root / part).exists():
                    missing.append(f"{command.command_id} names {part}")
    return missing


class TestRegistry:
    def test_every_registered_command_has_an_argument_vector(self) -> None:
        assert registry.VALIDATION_COMMANDS
        for command_id, command in registry.VALIDATION_COMMANDS.items():
            assert command.command_id == command_id
            assert command.argv and all(command.argv)
            assert command.proves.strip()

    def test_every_registered_pytest_target_exists_in_this_repository(self) -> None:
        """A registry entry naming a file nobody wrote is the old failure again.

        The capability registry was repaired because the controller believed in
        an executor the worker did not have. A command registry that names a
        missing test file is the same mistake one layer down.
        """
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        missing = missing_registry_targets(registry.VALIDATION_COMMANDS.values(), root)
        assert not missing, missing

    def test_an_unknown_identifier_fails_closed(self) -> None:
        with pytest.raises(registry.UnknownValidationCommand, match="no validation command"):
            registry.resolve(["rm-minus-rf"])

    def test_declaring_no_command_is_refused(self) -> None:
        # Otherwise a "validation" task could validate nothing and settle done.
        with pytest.raises(registry.UnknownValidationCommand, match="no validation command"):
            registry.resolve([])

    def test_a_shell_string_is_not_an_identifier(self) -> None:
        with pytest.raises(registry.UnknownValidationCommand):
            registry.resolve(["python3 -c 'print(1)'"])

    def test_duplicates_collapse_but_order_is_kept(self) -> None:
        resolved = registry.resolve(
            ["provider-routing-tests", "control-plane-tests", "provider-routing-tests"]
        )
        assert [c.command_id for c in resolved] == [
            "provider-routing-tests",
            "control-plane-tests",
        ]

    def test_an_unbounded_request_is_refused(self) -> None:
        with pytest.raises(registry.UnknownValidationCommand, match="at most"):
            registry.resolve(["control-plane-tests"] * (registry.MAX_COMMANDS_PER_TASK + 1))


class TestExecution:
    def test_a_passing_run_produces_evidence_naming_what_ran(self) -> None:
        def always_pass(argv, cwd, timeout):
            return subprocess.CompletedProcess(list(argv), 0, "2 passed\n", "")

        evidence = executor.run_validation(
            ["control-plane-compiles"], runner=always_pass, clock=iter([1.0, 1.5]).__next__
        )
        assert evidence["schema"] == executor.EVIDENCE_SCHEMA
        assert evidence["passed"] is True
        assert evidence["failed_command_ids"] == []
        row = evidence["results"][0]
        assert row["command_id"] == "control-plane-compiles"
        assert row["argv"][:3] == ["python3", "-m", "compileall"]
        assert row["exit_code"] == 0
        assert row["duration_seconds"] == 0.5
        assert row["output_digest"].startswith("sha256:")
        assert "2 passed" in row["output_tail"]

    def test_a_failing_command_makes_the_whole_run_fail(self) -> None:
        def fail_second(argv, cwd, timeout):
            code = 0 if "compileall" in argv else 1
            return subprocess.CompletedProcess(list(argv), code, "", "1 failed\n")

        evidence = executor.run_validation(
            ["control-plane-compiles", "control-plane-tests"], runner=fail_second
        )
        assert evidence["passed"] is False
        assert evidence["failed_command_ids"] == ["control-plane-tests"]

    def test_every_declared_command_runs_even_after_one_fails(self) -> None:
        """Stopping at the first failure hides the rest of the answer."""
        seen: list[str] = []

        def record(argv, cwd, timeout):
            seen.append(argv[-1])
            return subprocess.CompletedProcess(list(argv), 1, "", "boom\n")

        evidence = executor.run_validation(
            ["control-plane-compiles", "control-plane-tests"], runner=record
        )
        assert len(seen) == 2
        assert evidence["command_count"] == 2

    def test_a_timeout_is_a_failure_and_never_an_unknown(self) -> None:
        def hang(argv, cwd, timeout):
            raise subprocess.TimeoutExpired(list(argv), timeout, output="partial\n")

        evidence = executor.run_validation(["control-plane-compiles"], runner=hang)
        assert evidence["passed"] is False
        row = evidence["results"][0]
        assert row["timed_out"] is True
        assert row["exit_code"] is None
        assert "partial" in row["output_tail"]

    def test_a_runner_that_cannot_start_is_a_failure(self) -> None:
        def missing(argv, cwd, timeout):
            raise OSError("no such file")

        evidence = executor.run_validation(["control-plane-compiles"], runner=missing)
        assert evidence["passed"] is False
        assert evidence["results"][0]["runner_error"] == "OSError"

    def test_an_unknown_command_raises_rather_than_reporting_an_empty_pass(self) -> None:
        with pytest.raises(registry.UnknownValidationCommand):
            executor.run_validation(["not-a-command"], runner=lambda *a: None)

    def test_output_is_bounded_but_the_digest_covers_all_of_it(self) -> None:
        flood = "x" * (executor.OUTPUT_TAIL_CHARACTERS * 3)

        def noisy(argv, cwd, timeout):
            return subprocess.CompletedProcess(list(argv), 0, flood, "")

        evidence = executor.run_validation(["control-plane-compiles"], runner=noisy)
        row = evidence["results"][0]
        assert len(row["output_tail"]) == executor.OUTPUT_TAIL_CHARACTERS + 1
        assert row["output_digest"] == executor._digest(flood)


class TestTheLaneCannotSpend:
    def test_provider_credentials_are_removed_from_the_child_environment(self) -> None:
        source = {
            "ANTHROPIC_API_KEY": "secret",
            "OPENAI_API_KEY": "secret",
            "GEMINI_API_KEY": "secret",
            "GH_TOKEN": "secret",
            "GITHUB_TOKEN": "secret",
            "SOME_SERVICE_SECRET": "secret",
            "OC_GOVERNOR_MONTHLY_BUDGET_USD": "10",
            "PATH": "/usr/bin",
        }
        env = executor.sanitized_environment(source)
        assert env["PATH"] == "/usr/bin"
        for removed in source:
            if removed != "PATH":
                assert removed not in env

    def test_the_evidence_states_zero_provider_calls(self) -> None:
        def pass_all(argv, cwd, timeout):
            return subprocess.CompletedProcess(list(argv), 0, "", "")

        evidence = executor.run_validation(["control-plane-compiles"], runner=pass_all)
        assert evidence["safety"]["provider_calls"] is False
        assert evidence["safety"]["credentials_visible_to_commands"] is False


class TestRegistryTargetCheck:
    """The registry guard itself: it must accept modules and still catch missing targets."""

    @staticmethod
    def _command(*argv: str):
        from types import SimpleNamespace

        return SimpleNamespace(command_id="fixture", argv=argv)

    def test_an_existing_module_after_dash_m_is_accepted(self, tmp_path) -> None:
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "present.py").write_text("")
        command = self._command("python3", "-m", "scripts.present", "--flag")
        assert missing_registry_targets([command], tmp_path) == []

    def test_a_missing_module_after_dash_m_is_reported(self, tmp_path) -> None:
        (tmp_path / "scripts").mkdir()
        command = self._command("python3", "-m", "scripts.absent")
        assert missing_registry_targets([command], tmp_path) == [
            "fixture names module scripts.absent"
        ]

    def test_a_missing_path_is_still_reported(self, tmp_path) -> None:
        command = self._command("python3", "-m", "pytest", "tests/test_absent.py")
        assert missing_registry_targets([command], tmp_path) == [
            "fixture names tests/test_absent.py"
        ]

    def test_a_dotted_module_is_not_mistaken_for_a_missing_path(self, tmp_path) -> None:
        # The regression: "scripts.x" starts with "scripts" but is not a path.
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "x.py").write_text("")
        assert missing_registry_targets([self._command("python3", "-m", "scripts.x")], tmp_path) == []
