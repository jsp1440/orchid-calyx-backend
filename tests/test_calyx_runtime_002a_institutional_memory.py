import pytest

from runtime.institutional_memory import (
    InstitutionalMemoryRegistry,
    MemoryEvidence,
)


def evidence(source_id: str = "pr-222") -> tuple[MemoryEvidence, ...]:
    return (
        MemoryEvidence(
            source_type="github_pull_request",
            source_id=source_id,
            source_url=f"https://github.com/example/repo/pull/{source_id}",
        ),
    )


def test_memory_record_requires_provenance():
    registry = InstitutionalMemoryRegistry()
    with pytest.raises(ValueError):
        registry.create_record(
            category="decision",
            title="Use governed publication",
            summary="Publication requires review.",
            actor="calyx",
            evidence=(),
        )


def test_record_is_deterministic_and_idempotent():
    registry = InstitutionalMemoryRegistry()
    kwargs = {
        "category": "decision",
        "title": "Use World Plants backbone",
        "summary": "World Plants is the canonical taxonomic backbone.",
        "actor": "Jeff Parham",
        "evidence": evidence("decision-17"),
        "occurred_at": "2026-05-20T12:00:00+00:00",
    }
    first = registry.create_record(**kwargs)
    second = registry.create_record(**kwargs)
    assert first == second
    assert first.memory_id.startswith("mem-")
    assert registry.get(first.memory_id) == first


def test_search_ranks_matching_records_and_timeline_is_ordered():
    registry = InstitutionalMemoryRegistry()
    later = registry.create_record(
        category="engineering",
        title="Reasoning Ledger certification",
        summary="Certified the governed reasoning chain.",
        actor="calyx",
        evidence=evidence("pr-222"),
        occurred_at="2026-08-01T20:00:00+00:00",
    )
    earlier = registry.create_record(
        category="taxonomy",
        title="World Plants adoption",
        summary="Selected the taxonomic backbone.",
        actor="Jeff Parham",
        evidence=evidence("decision-17"),
        occurred_at="2026-05-20T12:00:00+00:00",
    )

    assert registry.search("reasoning certification") == (later,)
    assert registry.timeline() == (earlier, later)


def test_confidence_and_status_fail_closed():
    registry = InstitutionalMemoryRegistry()
    with pytest.raises(ValueError):
        registry.create_record(
            category="decision",
            title="Invalid confidence",
            summary="Must fail.",
            actor="calyx",
            evidence=evidence(),
            confidence=1.2,
        )
    with pytest.raises(ValueError):
        registry.create_record(
            category="decision",
            title="Invalid status",
            summary="Must fail.",
            actor="calyx",
            evidence=evidence(),
            status="deleted",
        )


def test_search_handles_score_and_time_ties():
    """Test that records with same score and occurred_at are ordered by memory_id."""
    registry = InstitutionalMemoryRegistry()
    # Create two records with identical score and occurred_at
    # They both match the query term "test" once
    record_a = registry.create_record(
        category="decision",
        title="Test alpha",
        summary="First test record.",
        actor="calyx",
        evidence=evidence("pr-111"),
        occurred_at="2026-05-20T12:00:00+00:00",
    )
    record_b = registry.create_record(
        category="decision",
        title="Test beta",
        summary="Second test record.",
        actor="calyx",
        evidence=evidence("pr-222"),
        occurred_at="2026-05-20T12:00:00+00:00",
    )

    # Both records match "test" exactly once, have the same occurred_at,
    # so they should be ordered by memory_id ascending
    results = registry.search("test")
    assert len(results) == 2
    assert results[0].memory_id <= results[1].memory_id
    # Verify they are in the order we expect (sorted by memory_id)
    assert results == tuple(sorted([record_a, record_b], key=lambda r: r.memory_id))


def test_search_stability_across_repeated_calls():
    """Test that repeated calls with the same input return identical results."""
    registry = InstitutionalMemoryRegistry()
    # Create multiple records with ties
    for i in range(5):
        registry.create_record(
            category="event",
            title=f"Milestone test {i}",
            summary="This is a test milestone.",
            actor="calyx",
            evidence=evidence(f"pr-{i}"),
            occurred_at="2026-06-15T10:00:00+00:00",
        )

    # Call search multiple times
    results_1 = registry.search("milestone test")
    results_2 = registry.search("milestone test")
    results_3 = registry.search("milestone test")

    # All results should be identical
    assert results_1 == results_2
    assert results_2 == results_3
    # Verify all records are returned
    assert len(results_1) == 5
