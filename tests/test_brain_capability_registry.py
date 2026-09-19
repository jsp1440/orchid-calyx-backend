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
    assert decisions["scientific_language_intake"]["eligible"] is False
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
