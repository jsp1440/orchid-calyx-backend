"""Regression coverage for the provider-free validation command registry."""

from scripts.oc_validation_commands import VALIDATION_COMMANDS, resolve


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
