"""Regression coverage for the provider-free validation command registry."""

from __future__ import annotations

import subprocess

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
