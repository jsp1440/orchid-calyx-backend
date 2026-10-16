from app.homepage_readiness.contracts import (
    REQUIRED_METRIC_KEYS,
    MetricState,
    ReadinessMetric,
    determine_homepage_ready,
)


def test_blocker_order_is_deterministic_with_unavailable_metrics():
    """Test that blockers are in sorted order when all required metrics are unavailable.

    This ensures that the order is deterministic across different PYTHONHASHSEED values.
    """
    # Create metrics that are unavailable for all required keys
    metrics = [
        ReadinessMetric(
            key=key,
            label=f"Label for {key}",
            state=MetricState.unavailable,
            source="test",
        )
        for key in REQUIRED_METRIC_KEYS
    ]

    # Determine readiness with all metrics unavailable
    ready, blockers = determine_homepage_ready(metrics, [])

    # Extract the blocker messages for required metrics not measured
    required_metric_blockers = [
        b for b in blockers if b.startswith("Required metric not measured:")
    ]

    # Verify they are in sorted order
    expected_blockers = [
        f"Required metric not measured: {k}" for k in sorted(REQUIRED_METRIC_KEYS)
    ]
    assert required_metric_blockers == expected_blockers

    # Verify homepage is not ready
    assert ready is False


def test_blocker_order_is_sorted_for_missing_metrics():
    """Test that blockers for missing metrics are in sorted order."""
    # Provide no metrics, so all required metrics are missing
    metrics = []

    # Determine readiness
    ready, blockers = determine_homepage_ready(metrics, [])

    # Extract the blocker messages for required metrics unavailable
    missing_metric_blockers = [
        b for b in blockers if b.startswith("Required metric unavailable:")
    ]

    # Verify they are in sorted order
    expected_missing = sorted(REQUIRED_METRIC_KEYS)
    actual_missing = [
        b.split("Required metric unavailable: ")[1] for b in missing_metric_blockers
    ]
    assert actual_missing == expected_missing

    # Verify homepage is not ready
    assert ready is False
