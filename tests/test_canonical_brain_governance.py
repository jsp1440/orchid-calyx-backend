from app.canonical_brain.fixtures import build_canonical_brain_fixture
from app.canonical_brain.governance import build_governance_report


def test_governance_report_is_deterministic_and_complete() -> None:
    registry = build_canonical_brain_fixture()

    first = build_governance_report(registry)
    second = build_governance_report(registry)

    assert first == second
    assert first.architecture_count == 9
    assert first.intent_count == 5
    assert first.aligned_architecture_count == 9
    assert first.intent_coverage_ratio == 1.0
    assert first.gaps == []


def test_every_architecture_has_intent_and_decision_coverage() -> None:
    registry = build_canonical_brain_fixture()
    report = build_governance_report(registry)

    assert report.gaps == []
    architectures = [
        record for record in registry.snapshot().objects
        if record.object_type == "architecture"
    ]
    for architecture in architectures:
        assert registry.aligned_intents(architecture.object_id)
        decisions = [
            related for related in registry.related(architecture.object_id, "documents")
            if related.object_type == "decision"
        ]
        assert decisions
