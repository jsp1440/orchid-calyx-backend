"""Regression coverage for the provider-free validation command registry."""

from __future__ import annotations

import subprocess
import sys

from scripts.oc_validation_commands import VALIDATION_COMMANDS, resolve


def test_autonomy_restart_continuity_proof_is_fixed_and_provider_free() -> None:
    command = VALIDATION_COMMANDS["autonomy-restart-continuity-tests"]

    assert command.argv == (
        "python3",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "tests/test_autonomy_process_restart_continuity.py",
    )
    assert "abrupt interpreter exit" in command.proves
    assert "three consecutive cycles" in command.proves
    assert "suppresses replayed work" in command.proves


def test_autonomy_restart_continuity_proof_command_executes() -> None:
    """Exercise the exact fixed argv that the provider-free worker will run."""
    command = VALIDATION_COMMANDS["autonomy-restart-continuity-tests"]
    result = subprocess.run(
        command.argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_bounded_lane_runtime_proof_is_fixed_and_provider_free() -> None:
    command = VALIDATION_COMMANDS["bounded-lane-runtime-tests"]

    assert command.argv == (
        "python3",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "tests/test_lane_runtime.py",
    )
    assert "three concurrent lane identities" in command.proves
    assert "unknown-cost honesty" in command.proves
    assert "absence of production mutation methods" in command.proves


def test_bounded_lane_runtime_proof_resolves_without_free_form_shell() -> None:
    assert resolve(["bounded-lane-runtime-tests"]) == [
        VALIDATION_COMMANDS["bounded-lane-runtime-tests"]
    ]


def test_bounded_lane_runtime_proof_command_executes() -> None:
    """Exercise the exact fixed argv that the provider-free worker will run."""
    command = VALIDATION_COMMANDS["bounded-lane-runtime-tests"]
    result = subprocess.run(
        command.argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "7 passed" in result.stdout


def test_calyx_product_advisory_is_fixed_and_provider_free() -> None:
    command = VALIDATION_COMMANDS["calyx-product-advisory"]

    assert command.argv == ("python3", "-m", "scripts.oc_brain_pulse", "--verify-calyx-product")
    assert "University module artifact" in command.proves
    assert "explicit no-action" in command.proves
    assert resolve(["calyx-product-advisory"]) == [command]


def test_calyx_product_advisory_command_executes() -> None:
    """Run the exact registered command used by the provider-free worker."""
    command = VALIDATION_COMMANDS["calyx-product-advisory"]
    result = subprocess.run(
        (sys.executable, *command.argv[1:]),
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert '"candidate_count": 1' in result.stdout
    assert '"independent": false' in result.stdout


def test_undeclared_imports_check_is_fixed_and_re_runs_discovery() -> None:
    command = VALIDATION_COMMANDS["undeclared-imports"]

    assert command.argv == (
        "python3",
        "-m",
        "scripts.oc_work_discovery",
        "--root",
        ".",
        "--check",
        "undeclared-import",
    )
    assert command.settles == ("undeclared-import",)
    assert "declares" in command.proves
    assert resolve(["undeclared-imports"]) == [command]


def test_the_app_import_check_settles_no_discovery_condition() -> None:
    # It proves the application imports. A lazy import of an undeclared
    # distribution passes it, which is how #1977 settled done and recurred.
    assert VALIDATION_COMMANDS["production-runtime-imports"].settles == ()


class TestConditionValidatorContract:
    """Every source with a condition validator is settled only by that validator."""

    def test_each_condition_source_maps_to_a_registered_command_that_settles_it(
        self,
    ) -> None:
        from scripts.oc_work_discovery import CHECKABLE_SOURCES, CONDITION_VALIDATORS

        assert CONDITION_VALIDATORS, "no source is bound to a condition validator"
        for source, command_id in CONDITION_VALIDATORS.items():
            command = VALIDATION_COMMANDS[command_id]
            assert source in command.settles, (source, command_id)
            # The validator re-runs the same discovery source, by name.
            assert source in CHECKABLE_SOURCES
            assert command.argv[-2:] == ("--check", source)

    def test_no_command_claims_to_settle_a_source_it_is_not_bound_to(self) -> None:
        from scripts.oc_work_discovery import CONDITION_VALIDATORS

        for command_id, command in VALIDATION_COMMANDS.items():
            for source in command.settles:
                assert CONDITION_VALIDATORS.get(source) == command_id, (
                    command_id,
                    source,
                )

    def test_discovery_binds_condition_sources_only_to_their_validator(
        self, tmp_path
    ) -> None:
        from scripts import oc_work_discovery as discovery

        (tmp_path / "requirements.txt").write_text("fastapi<0.116\n")
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "main.py").write_text("import starlette\n")
        (tmp_path / "runtime").mkdir()
        (tmp_path / "runtime" / "worker.py").write_text(
            "def go():\n    import httplib2\n"
        )
        found = discovery.discover_undeclared_imports(
            tmp_path,
            provided_by={"starlette": ["starlette"], "httplib2": ["httplib2"]},
        )
        assert sorted(c.remedy["distribution"] for c in found) == [
            "httplib2",
            "starlette",
        ]
        for candidate in found:
            assert (
                candidate.validation_command
                == discovery.CONDITION_VALIDATORS[candidate.source]
            )
