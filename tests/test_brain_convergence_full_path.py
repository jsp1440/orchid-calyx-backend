from dataclasses import replace

from runtime.brain_capability_registry import (
    CapabilityRegistry,
    canonical_brain_registry,
)
from runtime.calyx_queue_director import DevelopmentIntent, plan_calyx_refill


def _snapshot(**overrides):
    state = {
        "issues": [],
        "leases": [],
        "dispatch_fingerprints": [],
        "autonomous_prs": [],
    }
    state.update(overrides)
    return state


def _intent(**overrides):
    values = {
        "source_key": "brain-convergence-certification",
        "issue_number": 1498,
        "title": "Certify the governed Brain dependency path",
        "repo": "orchid-calyx-backend",
        "objective": "Prove verified Brain state reaches deterministic Queue Bridge",
        "acceptance_criteria": (
            "all canonical Brain dependencies are verified and eligible",
            "the unchanged intent is admitted exactly once",
            "protected work remains owner-gated",
        ),
        "required_capabilities": (
            "literature_candidate_handoff",
            "scientific_language_intake",
            "reasoning_ledger",
            "epistemic_memory",
            "data_intelligence",
            "executive_planning",
        ),
        "priority": 0,
    }
    values.update(overrides)
    return DevelopmentIntent(**values)


def test_full_brain_path_admits_once_and_remains_non_authoritative():
    registry = canonical_brain_registry()
    view = registry.orchestrator_view()

    assert view["completion"] == {
        "verified_eligible": 6,
        "total_capabilities": 6,
        "percent": 100.0,
    }
    assert view["read_only"] is True
    assert view["execution_authority"] is False
    assert view["publication_authority"] is False

    first = plan_calyx_refill(
        [_intent()],
        _snapshot(),
        reserve_depth=1,
        registry=registry,
    )
    assert first["status"] == "refill_planned"
    assert first["no_api_mode"] is True
    assert first["provider_launch_authorized"] is False
    assert len(first["proposals"]) == 1
    proposal = first["proposals"][0]
    assert proposal["source_ref"] == "#1498"
    assert proposal["required_capabilities"] == sorted(
        _intent().required_capabilities
    )

    replay = plan_calyx_refill(
        [_intent()],
        _snapshot(
            issues=[
                {
                    "state": "queued",
                    "material_fingerprint": proposal["material_fingerprint"],
                    "semantic_key": proposal["semantic_key"],
                }
            ]
        ),
        reserve_depth=1,
        registry=registry,
    )
    assert replay["proposals"] == []
    assert {
        rejection["reason"]
        for rejection in replay["rejections"]
    } & {"duplicate_fingerprint", "semantic_duplicate"}

    owner_gated = plan_calyx_refill(
        [_intent(protected_boundaries=("main-merge",))],
        _snapshot(),
        reserve_depth=1,
        registry=registry,
    )
    assert owner_gated["proposals"] == []
    assert owner_gated["calyx_parked"][0]["reason"] == "owner_gate"


def test_completion_percentage_is_derived_from_verified_dependency_state():
    canonical = canonical_brain_registry()
    data = canonical._items["data_intelligence"]
    incomplete_data = replace(
        data,
        status="PARTIAL",
        blockers=("certification missing",),
    )
    registry = CapabilityRegistry(
        tuple(
            incomplete_data if item.capability_id == "data_intelligence" else item
            for item in canonical._items.values()
        )
    )

    view = registry.orchestrator_view()
    by_id = {
        item["capability_id"]: item
        for item in view["capabilities"]
    }

    assert by_id["data_intelligence"]["eligibility"]["eligible"] is False
    assert view["completion"] == {
        "verified_eligible": 5,
        "total_capabilities": 6,
        "percent": 83.33,
    }
