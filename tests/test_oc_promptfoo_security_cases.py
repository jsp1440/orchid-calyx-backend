"""Offline red-team cases for the direct executor's tool guards.

Runs security/promptfoo/cases.yaml through the same harness the Promptfoo
provider uses, so CI enforces the cases without Node. Known gaps
(security/promptfoo/gaps.yaml) run as strict xfail: closing a gap turns this
red until the case moves to cases.yaml.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1] / "security" / "promptfoo"
sys.path.insert(0, str(HERE))

from oc_guard_harness import judge, load_cases, run_case

CASES = load_cases("cases.yaml")
GAPS = load_cases("gaps.yaml")


def test_case_ids_are_unique_and_gaps_do_not_overlap() -> None:
    ids = [c["id"] for c in CASES + GAPS]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_enforced_guard_case(case) -> None:
    ok, detail = judge(case, *run_case(case))
    assert ok, detail


@pytest.mark.xfail(strict=True, reason="open executor security finding; see gaps.yaml")
@pytest.mark.parametrize("case", GAPS, ids=lambda c: f"{c['finding']}-{c['id']}")
def test_known_gap(case) -> None:
    ok, detail = judge(case, *run_case(case))
    assert ok, detail


def test_sandbox_never_touches_the_real_repository() -> None:
    real = Path(__file__).resolve().parents[1] / "app" / "atlas" / "projection.py"
    before = real.read_bytes() if real.exists() else None
    run_case(
        {
            "tool": "write_file",
            "input": {"path": "app/atlas/projection.py", "content": "X"},
            "expect": "ALLOWED",
        }
    )
    assert (real.read_bytes() if real.exists() else None) == before


def test_promptfoo_config_is_generated_from_cases() -> None:
    proc = subprocess.run(
        [sys.executable, str(HERE / "build_config.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout
