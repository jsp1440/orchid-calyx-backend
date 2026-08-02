def test_calyx_certification_expected_failure_round2() -> None:
    """Disposable certification failure; Calyx should repair only this assertion."""
    assert 1 == 2, "CALYX_CERTIFICATION_EXPECTED_FAILURE_ROUND2"
