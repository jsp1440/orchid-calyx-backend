from app.canonical_brain.fixtures import build_canonical_brain_fixture
from app.canonical_brain.governance import build_governance_report


def test_governance_report_is_deterministic_and_exposes_real_gaps() -> None:
    registry = build_canonical_brain_fixture()

    first = build_governance_report(registry)
    second = build_governance_report(registry)

    assert first == second
    assert first.architecture_count == 9
    assert first.intent_count == 2
    assert first.aligned_architecture_count == 3
    assert first.intent_coverage_ratio == 3 / 9
    assert any(gap.object_id == "architecture:mission-control" for gap in first.gaps)
    assert any(gap.gap_type == "missing_decision_record" for gap in first.gaps)


def test_every_gap_points_to_a_registered_architecture() -> None:
    registry = build_canonical_brain_fixture()
    report = build_governance_report(registry)

    for gap in report.gaps:
        record = registry.get(gap.object_id)
        assert record is not None
        assert record.object_type == "architecture"
