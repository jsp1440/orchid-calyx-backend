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
    assert decisions["reasoning_ledger"]["eligible"] is False
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
