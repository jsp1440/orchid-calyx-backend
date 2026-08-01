"""Disposable deterministic failure for Calyx preproduction certification.

This file exists only on the certification branch and must never be merged.
"""


def test_calyx_certification_failure_is_detected() -> None:
    """Fail deterministically so Calyx can inspect and repair the draft PR."""
    assert 1 == 2, "CALYX_CERTIFICATION_EXPECTED_FAILURE"
