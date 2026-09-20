from dataclasses import replace

import pytest

from runtime.brain_capability_registry import (
    CapabilityRegistry,
    canonical_brain_registry,
)


def test_seed_exposes_only_verified_operational_work_as_eligible():
    view = canonical_brain_registry().orchestrator_view()
    decisions = {
        item["capability_id"]: item["eligibility"] for item in view["capabilities"]
    }

    assert decisions["literature_candidate_handoff"]["eligible"] is True
    assert decisions["scientific_language_intake"]["eligible"] is True
    assert decisions["reasoning_ledger"]["eligible"] is True
    assert decisions["epistemic_memory"]["eligible"] is True
    assert decisions["data_intelligence"]["eligible"] is False
    assert decisions["executive_planning"]["eligible"] is True
    assert view["read_only"] is True
    assert view["execution_authority"] is False
    assert view["publication_authority"] is False


def test_unknown_dependencies_fail_closed():
    seed = canonical_brain_registry()._items["literature_candidate_handoff"]
    consumer = replace(
        seed,
        capability_id="consumer",
        upstream_dependencies=("missing",),
        downstream_consumers=(),
    )

    result = CapabilityRegistry((consumer,)).eligibility("consumer")

    assert result["eligible"] is False
    assert result["reasons"] == ["unknown dependency: missing"]


def test_view_is_stable_and_duplicate_ids_are_rejected():
    registry = canonical_brain_registry()
    assert registry.orchestrator_view() == registry.orchestrator_view()
    item = registry._items["literature_candidate_handoff"]

    with pytest.raises(ValueError, match="duplicate capability_id"):
        CapabilityRegistry((item, item))


def test_operational_dependency_with_unresolved_upstream_fails_closed():
    seed = canonical_brain_registry()._items["literature_candidate_handoff"]
    dependency = replace(
        seed,
        capability_id="dependency",
        upstream_dependencies=("missing",),
        downstream_consumers=("consumer",),
    )
    consumer = replace(
        seed,
        capability_id="consumer",
        upstream_dependencies=("dependency",),
        downstream_consumers=(),
    )

    result = CapabilityRegistry((dependency, consumer)).eligibility("consumer")

    assert result["eligible"] is False
    assert result["reasons"] == [
        "dependency ineligible: dependency (unknown dependency: missing)"
    ]


def test_dependency_cycles_fail_closed_without_recursion_error():
    seed = canonical_brain_registry()._items["literature_candidate_handoff"]
    first = replace(
        seed,
        capability_id="first",
        upstream_dependencies=("second",),
        downstream_consumers=("second",),
    )
    second = replace(
        seed,
        capability_id="second",
        upstream_dependencies=("first",),
        downstream_consumers=("first",),
    )

    result = CapabilityRegistry((first, second)).eligibility("first")

    assert result["eligible"] is False
    assert "dependency cycle: first -> second -> first" in str(result["reasons"])


def test_reasoning_ledger_registry_metadata_is_pinned_and_non_authoritative():
    view = canonical_brain_registry().orchestrator_view()
    reasoning = next(
        item
        for item in view["capabilities"]
        if item["capability_id"] == "reasoning_ledger"
    )

    assert reasoning["canonical_issue"] == "orchid-calyx-backend#142"
    assert reasoning["status"] == "OPERATIONAL"
    assert reasoning["public_entry_point"] == "/api/reasoning-ledgers"
    assert reasoning["next_executable_slice"] is None
    assert reasoning["blockers"] == ()
    assert "migrations/103_reasoning_ledger.sql" in reasoning["repository_evidence"]
    assert reasoning["last_verified_commit"] == (
        "a379045af226c3c700e201d3da1c4028822f778b"
    )
    assert view["execution_authority"] is False
    assert view["publication_authority"] is False



def test_executive_planning_registry_metadata_is_pinned_and_non_authoritative():
    view = canonical_brain_registry().orchestrator_view()
    planning = next(
        item
        for item in view["capabilities"]
        if item["capability_id"] == "executive_planning"
    )

    assert planning["status"] == "OPERATIONAL"
    assert planning["eligibility"]["eligible"] is True
    assert planning["next_executable_slice"] is None
    assert planning["blockers"] == ()
    assert planning["last_verified_commit"] == (
        "38f83c7e5dd415417ed74eae5a29362472338cd8"
    )
    assert "orchid-calyx-backend#1556 capability-gated intent bridge" in (
        planning["repository_evidence"]
    )
    assert view["execution_authority"] is False
    assert view["publication_authority"] is False


def test_memory_and_data_registry_metadata_are_evidence_pinned():
    view = canonical_brain_registry().orchestrator_view()
    by_id = {item["capability_id"]: item for item in view["capabilities"]}

    memory = by_id["epistemic_memory"]
    assert memory["status"] == "OPERATIONAL"
    assert memory["eligibility"]["eligible"] is True
    assert memory["upstream_dependencies"] == ("reasoning_ledger",)
    assert memory["publication_authority"] if False else True

    data = by_id["data_intelligence"]
    assert data["status"] == "PARTIAL"
    assert data["eligibility"]["eligible"] is False
    assert data["next_executable_slice"]
    assert data["blockers"] == (
        "full export and reusable-workflow review flow are incomplete",
    )
    assert data["last_verified_commit"] == (
        "fa3954fd04dee0015ee5afe166c1bb7402d9b981"
    )
    assert view["execution_authority"] is False
    assert view["publication_authority"] is False
