"""FIL-001 functional-edge compatibility, planning and governance."""

from __future__ import annotations

import json
from dataclasses import replace
from itertools import pairwise
from pathlib import Path

import jsonschema
import pytest

from app.functional_interaction.compatibility import check_edge
from app.functional_interaction.contracts import (
    AutonomyClass,
    ContractError,
    HealthSpec,
    PortSpec,
    ProvenanceRequirement,
)
from app.functional_interaction.governance import (
    MAX_DRY_RUN_COST_UNITS,
    WITHHELD_AUTHORITY,
    GovernanceAction,
    evaluate_plan,
)
from app.functional_interaction.planner import SourceArtifact, plan_workflow
from app.functional_interaction.registry import FunctionalRegistry
from app.functional_interaction.scientific_demo import (
    SOURCE,
    demo_descriptors,
    demo_registry,
)

ROOT = Path(__file__).resolve().parents[1]
EDGE_SCHEMA = json.loads(
    (ROOT / "contracts" / "oc-fil-functional-edge.v1.json").read_text()
)
CHAIN = [
    "fil.literature.claim-transducer",
    "fil.taxonomy.backbone-adaptor",
    "fil.evidence.candidate-validator",
    "fil.traitbank.candidate-buffer",
    "fil.reasoning.ledger-integrator",
]


def _d(capability_id: str):
    return demo_registry().get(capability_id)


def _edge(producer, consumer, **kwargs):
    edge = check_edge(
        producer, producer.outputs[0].name, consumer, consumer.inputs[0].name, **kwargs
    )
    jsonschema.validate(edge.to_dict(), EDGE_SCHEMA)
    assert edge.compatible is (not edge.blocking_reasons)
    return edge


def test_adjacent_chain_edges_are_compatible_and_carry_conditions_forward():
    conditions = SOURCE.conditions
    for producer_id, consumer_id in pairwise(CHAIN):
        edge = _edge(_d(producer_id), _d(consumer_id), upstream_conditions=conditions)
        assert edge.compatible, (edge.edge_id, edge.blocking_reasons)
        conditions = edge.carried_conditions
    assert set(conditions) >= {
        "source_anchored",
        "claims_anchored",
        "evidence_state_assigned",
        "candidate_only",
    }


def test_validator_to_buffer_filters_non_provisional_states_as_an_advisory():
    edge = _edge(_d(CHAIN[2]), _d(CHAIN[3]))
    assert edge.compatible
    assert edge.admitted_evidence_states == ("PROVISIONAL",)
    assert edge.advisories == ("EVIDENCE_STATES_FILTERED:REJECTED,UNKNOWN",)


def test_type_mismatch_and_inadmissible_state_and_missing_precondition_each_block():
    edge = _edge(_d(CHAIN[0]), _d(CHAIN[3]))
    assert edge.blocking_reasons == (
        "SEMANTIC_TYPE_MISMATCH",
        "EVIDENCE_STATE_INADMISSIBLE",
        "PRECONDITION_UNSATISFIED:evidence_state_assigned",
    )


def test_subtype_output_satisfies_supertype_input_but_not_the_reverse():
    validator, adaptor = _d(CHAIN[2]), _d(CHAIN[1])
    widened = replace(
        adaptor,
        inputs=(PortSpec("claims", "oc:ExtractedClaimBatch", ("PROVISIONAL",)),),
        preconditions=(),
    )
    assert "SEMANTIC_TYPE_MISMATCH" not in _edge(validator, widened).blocking_reasons
    narrowed = replace(
        validator,
        inputs=(PortSpec("linked_claims", "oc:ValidatedClaimBatch", ("UNKNOWN",)),),
        preconditions=(),
    )
    assert "SEMANTIC_TYPE_MISMATCH" in _edge(adaptor, narrowed).blocking_reasons


def test_preconditions_from_upstream_survive_only_a_chain_preserving_producer():
    adaptor, validator = _d(CHAIN[1]), _d(CHAIN[2])
    assert _edge(
        adaptor, validator, upstream_conditions=("claims_anchored",)
    ).compatible
    dropping = replace(adaptor, provenance=ProvenanceRequirement(preserves_chain=False))
    edge = _edge(dropping, validator, upstream_conditions=("claims_anchored",))
    assert "PRECONDITION_UNSATISFIED:claims_anchored" in edge.blocking_reasons
    assert "PROVENANCE_CHAIN_BROKEN" in edge.blocking_reasons


def test_autonomy_classes_shape_the_edge():
    producer, consumer = _d(CHAIN[3]), _d(CHAIN[4])
    upstream = ("evidence_state_assigned",)
    assert _edge(
        producer,
        replace(consumer, autonomy_class=AutonomyClass.HUMAN_APPROVAL),
        upstream_conditions=upstream,
    ).requires_human_gate
    proposal = _edge(
        producer,
        replace(consumer, autonomy_class=AutonomyClass.PROPOSAL_ONLY),
        upstream_conditions=upstream,
    )
    assert proposal.compatible and "PROPOSAL_ONLY" in proposal.advisories
    prohibited = _edge(
        producer,
        replace(consumer, autonomy_class=AutonomyClass.PROHIBITED),
        upstream_conditions=upstream,
    )
    assert prohibited.blocking_reasons == ("AUTONOMY_PROHIBITED",)


def test_provider_consumer_parks_under_no_api_and_unimplemented_consumer_cannot_run():
    integrator, explainer = _d(CHAIN[4]), _d("fil.reasoning.prose-explainer")
    upstream = ("human_review_required",)
    parked = _edge(integrator, explainer, upstream_conditions=upstream)
    assert parked.blocking_reasons == (
        "PROVIDER_PARKED_NO_API",
        "CAPABILITY_NOT_EXECUTABLE:DOCUMENTED_ONLY",
    )
    allowed_api = _edge(
        integrator, explainer, upstream_conditions=upstream, no_api_mode=False
    )
    assert allowed_api.blocking_reasons == (
        "CAPABILITY_NOT_EXECUTABLE:DOCUMENTED_ONLY",
    )


def test_unknown_port_name_is_a_contract_error():
    with pytest.raises(ContractError, match="UNKNOWN_OUTPUT_PORT"):
        check_edge(_d(CHAIN[0]), "nope", _d(CHAIN[1]), "claims")


def test_planner_finds_the_scientific_chain_deterministically():
    first = plan_workflow(demo_registry(), source=SOURCE, goal_type="oc:ReasoningDraft")
    second = plan_workflow(
        demo_registry(), source=SOURCE, goal_type="oc:ReasoningDraft"
    )
    assert [step.capability_id for step in first.steps] == CHAIN
    assert first.plan_id == second.plan_id
    assert first.to_dict() == second.to_dict()
    assert first.source_edge is not None and first.source_edge.compatible
    assert all(edge.compatible for edge in first.edges)
    assert first.to_dict()["execution_authority"] is False


def test_planner_order_is_independent_of_registration_order():
    reversed_registry = FunctionalRegistry(tuple(reversed(demo_descriptors())))
    plan = plan_workflow(
        reversed_registry, source=SOURCE, goal_type="oc:ReasoningDraft"
    )
    assert [step.capability_id for step in plan.steps] == CHAIN


def test_source_without_required_condition_cannot_start_the_chain():
    plan = plan_workflow(
        demo_registry(),
        source=SourceArtifact("oc:LiteraturePassageBatch", ("UNKNOWN",), conditions=()),
        goal_type="oc:ReasoningDraft",
    )
    assert not plan.found
    rejected = {
        item["edge_id"]: item["blocking_reasons"] for item in plan.rejected_edges
    }
    assert rejected["source->fil.literature.claim-transducer@1.0.0#passages"] == [
        "PRECONDITION_UNSATISFIED:source_anchored"
    ]


def test_provider_goal_has_no_plan_under_no_api_and_explains_why():
    plan = plan_workflow(
        demo_registry(), source=SOURCE, goal_type="oc:PlainLanguageExplanation"
    )
    assert not plan.found
    rejected = {
        item["edge_id"]: item["blocking_reasons"] for item in plan.rejected_edges
    }
    key = "fil.reasoning.ledger-integrator@1.0.0#reasoning->fil.reasoning.prose-explainer@0.1.0#reasoning"
    assert "PROVIDER_PARKED_NO_API" in rejected[key]
    decision = evaluate_plan(plan)
    assert decision.action is GovernanceAction.REFUSE
    assert decision.reasons == ("NO_COMPATIBLE_PLAN",)


def _implemented_explainer_registry() -> FunctionalRegistry:
    descriptors = [
        replace(d, health=HealthSpec(status="PARTIAL"))
        if d.capability_id == "fil.reasoning.prose-explainer"
        else d
        for d in demo_descriptors()
    ]
    return FunctionalRegistry(tuple(descriptors))


def test_implemented_provider_step_parks_under_no_api_and_owner_gates_otherwise():
    plan = plan_workflow(
        _implemented_explainer_registry(),
        source=SOURCE,
        goal_type="oc:PlainLanguageExplanation",
        no_api_mode=False,
    )
    assert (
        plan.found and plan.steps[-1].capability_id == "fil.reasoning.prose-explainer"
    )
    assert plan.requires_human_gate
    parked = evaluate_plan(plan, no_api_mode=True)
    assert parked.action is GovernanceAction.OWNER_GATE  # class B outranks parking
    assert "NO_API_PROVIDER_CAPABILITY:natural-language-explanation" in parked.reasons
    assert "AUTONOMY_CLASS_B:fil.reasoning.prose-explainer" in parked.reasons
    spend = evaluate_plan(plan, no_api_mode=False)
    assert (
        "PROVIDER_SPEND_NOT_AUTHORIZED_BY_FIL:natural-language-explanation"
        in spend.reasons
    )
    assert spend.dry_run_authorized is False


def test_class_c_provider_step_parks_rather_than_running():
    descriptors = [
        replace(
            d,
            health=HealthSpec(status="PARTIAL"),
            autonomy_class=AutonomyClass.PROPOSAL_ONLY,
        )
        if d.capability_id == "fil.reasoning.prose-explainer"
        else d
        for d in demo_descriptors()
    ]
    plan = plan_workflow(
        FunctionalRegistry(tuple(descriptors)),
        source=SOURCE,
        goal_type="oc:PlainLanguageExplanation",
        no_api_mode=False,
    )
    decision = evaluate_plan(plan, no_api_mode=True)
    assert decision.action is GovernanceAction.OWNER_GATE
    assert (
        "AUTONOMY_CLASS_C_PROPOSAL_ONLY:fil.reasoning.prose-explainer"
        in decision.reasons
    )


def test_governance_allows_only_dry_run_and_never_grants_other_authority():
    plan = plan_workflow(demo_registry(), source=SOURCE, goal_type="oc:ReasoningDraft")
    decision = evaluate_plan(plan)
    assert decision.action is GovernanceAction.ALLOW_DRY_RUN
    record = decision.to_dict()
    for key, value in WITHHELD_AUTHORITY.items():
        assert record[key] is value is False
    production = evaluate_plan(plan, mode="production")
    assert production.action is GovernanceAction.OWNER_GATE
    assert production.reasons == ("FIL_001_HAS_NO_AUTHORITY_FOR_MODE:production",)


def test_governance_refuses_prohibited_steps_and_cost_overruns():
    plan = plan_workflow(demo_registry(), source=SOURCE, goal_type="oc:ReasoningDraft")
    prohibited_step = replace(
        plan.steps[-1],
        permissions=("publish",),
        autonomy_class=AutonomyClass.PROHIBITED,
    )
    tampered = replace(plan, steps=(*plan.steps[:-1], prohibited_step))
    decision = evaluate_plan(tampered)
    assert decision.action is GovernanceAction.REFUSE
    assert "AUTONOMY_CLASS_D:fil.reasoning.ledger-integrator" in decision.reasons
    assert (
        "PROHIBITED_PERMISSION:fil.reasoning.ledger-integrator:publish"
        in decision.reasons
    )

    from app.functional_interaction.contracts import BudgetRequirement

    expensive = replace(
        plan.steps[0], budget=BudgetRequirement(cost_units_max=MAX_DRY_RUN_COST_UNITS)
    )
    over = evaluate_plan(replace(plan, steps=(expensive, *plan.steps[1:])))
    assert over.action is GovernanceAction.REFUSE
    assert any(reason.startswith("COST_UNITS_EXCEEDED:") for reason in over.reasons)


def test_max_depth_bounds_the_search():
    plan = plan_workflow(
        demo_registry(), source=SOURCE, goal_type="oc:ReasoningDraft", max_depth=4
    )
    assert not plan.found
    with pytest.raises(ContractError, match="NON_POSITIVE_PLAN_DEPTH"):
        plan_workflow(
            demo_registry(), source=SOURCE, goal_type="oc:ReasoningDraft", max_depth=0
        )
