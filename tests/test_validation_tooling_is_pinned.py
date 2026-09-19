"""The workflows that gate autonomous work must pin their validation tooling.

CI installed `pytest ruff` unpinned, so the runner always took the newest
release. A contributor on an older ruff got a clean local run and pushed a
commit CI then failed on rules their version did not carry; the same commit
could go green today and red tomorrow with no change to the code. Issue #1501
records two such cycles in a single session (PR #1483 RUF059; PR #1500 UP037 and
ISC004), each clean on local ruff 0.15.8 and each red on CI's 0.16.8.

These tests pin the arrangement rather than the outcome: the gating workflows
install from `requirements-dev.txt`, and that file states exact versions a
contributor can install to reproduce CI's verdict.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEV_REQUIREMENTS = REPO_ROOT / "requirements-dev.txt"

#: The workflows that decide whether autonomous work is allowed to advance.
GATING_WORKFLOWS = (
    ".github/workflows/orchid-autonomous-validation.yml",
    ".github/workflows/orchid-completion-lane.yml",
)

#: `pip install ... pytest` / `... ruff` with no version attached.
UNPINNED_INSTALL = re.compile(
    r"^\s*(?:python3?\s+-m\s+)?pip\s+install\b(?P<args>[^\n]*)", re.MULTILINE
)
PINNED_TOOL = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s#]+)\s*$")


def _dev_requirements() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in DEV_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = PINNED_TOOL.match(stripped)
        assert match, f"{stripped!r} is not an exact pin; use name==version"
        pins[match.group("name").lower()] = match.group("version")
    return pins


def test_dev_requirements_pins_the_linter_and_test_runner_exactly():
    pins = _dev_requirements()
    for tool in ("ruff", "pytest"):
        assert tool in pins, f"{tool} must be pinned in requirements-dev.txt"
        # An exact version, not a range: a range reintroduces the drift.
        assert re.fullmatch(r"\d+(\.\d+)*", pins[tool]), (
            f"{tool}=={pins[tool]} is not an exact release"
        )


def test_dev_requirements_says_how_to_bump_it():
    """A contributor has to be able to find the version and the bump rule here."""
    text = DEV_REQUIREMENTS.read_text(encoding="utf-8")
    assert "pip install -r requirements-dev.txt" in text
    assert "#1501" in text


@pytest.mark.parametrize("workflow", GATING_WORKFLOWS)
def test_gating_workflow_installs_tooling_from_the_pinned_file(workflow: str):
    path = REPO_ROOT / workflow
    text = path.read_text(encoding="utf-8")
    assert "requirements-dev.txt" in text, (
        f"{workflow} must install validation tooling from requirements-dev.txt"
    )


@pytest.mark.parametrize("workflow", GATING_WORKFLOWS)
def test_gating_workflow_never_installs_pytest_or_ruff_unpinned(workflow: str):
    path = REPO_ROOT / workflow
    offending = []
    for match in UNPINNED_INSTALL.finditer(path.read_text(encoding="utf-8")):
        args = match.group("args")
        if "-r " in args:
            continue
        for tool in ("pytest", "ruff"):
            # Bare `pytest`/`ruff`, not `pytest==9.1.1` and not `pytest-asyncio`.
            if re.search(rf"(?<![\w-]){tool}(?![\w.=<>-])", args):
                offending.append(match.group(0).strip())
                break
    assert not offending, (
        f"{workflow} installs validation tooling without a version: {offending}"
    )
