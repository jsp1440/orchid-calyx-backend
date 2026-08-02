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
