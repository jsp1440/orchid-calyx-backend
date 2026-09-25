"""The always-failing certification fixture must stay out of the default suite.

``tests/calyx_certification/test_deterministic_failure_round2.py`` is a deliberate,
disposable failure for the CALYX-AGENT-007 repair harness. It must remain in the
repository and remain selectable, but it must not turn the repository-wide suite
red on every run. The marker registered in ``tests/conftest.py`` deselects it
unless the caller asks for it, by marker expression or by naming the file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FIXTURE = Path("tests/calyx_certification/test_deterministic_failure_round2.py")
NODE_ID = f"{FIXTURE}::test_calyx_certification_expected_failure_round2"


def _collect(*args: str) -> str:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:randomly",
            "--collect-only",
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout + proc.stderr


def test_fixture_is_marked_and_the_marker_is_registered():
    assert "@pytest.mark.calyx_certification_fixture" in FIXTURE.read_text()
    assert "calyx_certification_fixture" in _collect("--markers")


def test_default_collection_of_the_directory_deselects_the_fixture():
    output = _collect(str(FIXTURE.parent))
    assert NODE_ID not in output
    assert "1 deselected" in output


def test_marker_expression_selects_the_fixture():
    output = _collect(str(FIXTURE.parent), "-m", "calyx_certification_fixture")
    assert NODE_ID in output
    assert "deselected" not in output


def test_naming_the_file_selects_the_fixture():
    output = _collect(str(FIXTURE))
    assert NODE_ID in output
    assert "deselected" not in output
