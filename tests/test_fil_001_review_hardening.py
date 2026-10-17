"""Regression tests for the independent checker's FIL-001A findings.

Each test reproduces a scenario the checker executed against head 0aba32c and
asserts the fail-closed behaviour now required.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from app.functional_interaction import value_semantics as vs
from app.functional_interaction.contracts import AutonomyClass, PortSpec
from app.functional_interaction.dry_run import HandlerResult, execute_dry_run
from app.functional_interaction.governance import (
    GovernanceAction,
    GovernanceDecision,
    evaluate_plan,
)
from app.functional_interaction.planner import SourceArtifact, plan_workflow
from app.functional_interaction.registry import FunctionalRegistry
from app.functional_interaction.scientific_demo import (
    SOURCE,
    build_handlers,
    demo_descriptors,
    demo_registry,
    load_fixture,
    source_payload,
)


def _plan():
    return plan_workflow(demo_registry(), source=SOURCE, goal_type="oc:ReasoningDraft")


def test_forged_allow_decision_cannot_run_a_prohibited_step():
    plan = _plan()
    prohibited = replace(plan.steps[0], autonomy_class=AutonomyClass.PROHIBITED)
    tampered = replace(plan, steps=(prohibited, *plan.steps[1:]))
    assert evaluate_plan(tampered).action is GovernanceAction.REFUSE
    forged = GovernanceDecision(
        tampered.plan_id, "dry_run", GovernanceAction.ALLOW_DRY_RUN, ()
    )
    calls: list[str] = []
    handlers = {
        step.capability_id: (lambda payload, key=step.capability_id: calls.append(key))
        for step in tampered.steps
    }
    report = execute_dry_run(tampered, forged, handlers, {})
    assert calls == []
    assert not report.succeeded
    assert {r.failure_reason for r in report.receipts} == {"GOVERNANCE_REFUSE"}
    assert report.decision.action is GovernanceAction.REFUSE


def test_authorized_decision_that_does_not_reproduce_blocks_every_step():
    plan = _plan()
    looser = GovernanceDecision(
        plan.plan_id, "dry_run", GovernanceAction.ALLOW_DRY_RUN, ("CALLER_SAID_SO",)
    )
    report = execute_dry_run(plan, looser, build_handlers(load_fixture()), {})
    assert {r.failure_reason for r in report.receipts} == {
        "GOVERNANCE_DECISION_NOT_REPRODUCED"
    }


def test_hand_built_plan_with_hidden_type_mismatch_is_refused():
    plan = _plan()
    # Drop a middle step and its edges: the remaining steps no longer connect.
    broken = replace(plan, steps=(plan.steps[0], *plan.steps[2:]), edges=())
    decision = evaluate_plan(broken)
    assert decision.action is GovernanceAction.REFUSE
    assert any(r.startswith("RECOMPUTED_EDGE_INCOMPATIBLE:") for r in decision.reasons)
    assert any(r.startswith("PLAN_EDGES_INCONSISTENT:") for r in decision.reasons)


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        ({"output": 1}, "HANDLER_CONTRACT_RESULT_TYPE:dict"),
        (
            HandlerResult(
                output={"bad": {1, 2}},
                established=("taxon_resolution_recorded",),
                evidence_states=("PROVISIONAL",),
                provenance=("fixture://x",),
            ),
            "RESULT_NOT_RECORDABLE:TypeError",
        ),
    ],
)
def test_malformed_handler_results_become_blocked_receipts(result, reason):
    fixture = load_fixture()
    plan = _plan()
    handlers = build_handlers(fixture)
    target = plan.steps[1]
    handlers[target.capability_id] = lambda payload: result
    if isinstance(result, HandlerResult):
        # Satisfy every declared postcondition so only serializability fails.
        result = replace(
            result,
            established=target.effects,
            evidence_states=target.outputs[0].evidence_states[:1],
        )
        handlers[target.capability_id] = lambda payload: result
    report = execute_dry_run(
        plan, evaluate_plan(plan), handlers, source_payload(fixture)
    )
    assert report.receipts[1].failure_reason == reason
    assert all(r.failure_reason == "UPSTREAM_BLOCKED:1" for r in report.receipts[2:])


def test_human_only_evidence_state_inside_the_output_is_refused():
    fixture = load_fixture()
    plan = _plan()
    handlers = build_handlers(fixture)
    target = plan.steps[1]
    honest = handlers[target.capability_id]

    def smuggling(payload):
        result = honest(payload)
        return replace(result, output={**result.output, "evidence_state": "VERIFIED"})

    handlers[target.capability_id] = smuggling
    report = execute_dry_run(
        plan, evaluate_plan(plan), handlers, source_payload(fixture)
    )
    assert (
        report.receipts[1].failure_reason
        == "HUMAN_ONLY_EVIDENCE_STATE_IN_OUTPUT:VERIFIED"
    )


def test_planner_is_polynomial_over_mutually_compatible_descriptors():
    base = next(
        d
        for d in demo_descriptors()
        if d.capability_id == "fil.taxonomy.backbone-adaptor"
    )
    port = base.inputs[0]
    loops = tuple(
        replace(
            base,
            capability_id=f"fil.test.loop-{i:02d}",
            inputs=(port,),
            outputs=(PortSpec(port.name, port.semantic_type, port.evidence_states),),
            preconditions=(),
            effects=(),
        )
        for i in range(12)
    )
    registry = FunctionalRegistry(loops)
    source = SourceArtifact(port.semantic_type, port.evidence_states, SOURCE.conditions)
    started = time.perf_counter()
    plan = plan_workflow(registry, source=source, goal_type="oc:ReasoningDraft")
    assert not plan.found
    assert time.perf_counter() - started < 2.0


@pytest.mark.parametrize(
    ("predicate", "values", "expected"),
    [
        ("color", [("white", None, None), ("White", None, None)], vs.AGREEMENT),
        (
            "color",
            [("pale-yellow", None, None), ("pale yellow", None, None)],
            vs.AGREEMENT,
        ),
        ("color", [("white", None, None), ("red", None, None)], vs.CONTRADICTION),
        ("measurement", [(None, 3, "cm"), (None, 30, "mm")], vs.AGREEMENT),
        (
            "measurement",
            [(None, 12, "mm"), (None, 12, "cm")],
            vs.VARIATION_AT_UNSTATED_LEVEL,
        ),
        ("measurement", [(None, 12, "mm"), (None, 4, "g")], vs.INCOMMENSURABLE_UNITS),
        (
            "measurement",
            [(None, 12, "mm"), ("large", None, None)],
            vs.INCOMMENSURABLE_VALUES,
        ),
        (
            "ecological_relationship",
            [("bee a", None, None), ("bee b", None, None)],
            vs.MULTIPLE_VALUES_PERMITTED,
        ),
    ],
)
def test_value_semantics_only_calls_exclusive_categories_a_contradiction(
    predicate, values, expected
):
    keys = [vs.value_key(object_value=o, numeric_value=n, unit=u) for o, n, u in values]
    assert vs.classify(predicate, keys) == expected


# --- Copilot review (#1808) -------------------------------------------------


def test_plan_id_binds_every_material_descriptor_field():
    plan = _plan()
    for change in (
        {"autonomy_class": AutonomyClass.PROPOSAL_ONLY},
        {"permissions": ("candidate_generation", "read_only_research")},
        {"health": replace(plan.steps[0].health, evidence=("changed",))},
    ):
        changed = replace(
            plan, steps=(replace(plan.steps[0], **change), *plan.steps[1:])
        )
        assert changed.plan_id != plan.plan_id
        stale = evaluate_plan(plan)
        with pytest.raises(ValueError, match="GOVERNANCE_DECISION_PLAN_MISMATCH"):
            execute_dry_run(changed, stale, {}, {})


@pytest.mark.parametrize("reason", ["BAD REASON", "BAD-REASON", "bad_reason", ""])
def test_failure_reasons_must_match_the_schema_pattern(reason):
    from app.functional_interaction.contracts import ContractError, HealthSpec

    with pytest.raises(ContractError, match="INVALID_FAILURE_REASON"):
        HealthSpec(status="PARTIAL", failure_reasons=(reason,))


def test_blocked_receipt_never_records_the_rejected_evidence_state():
    import json as _json
    from pathlib import Path

    import jsonschema

    schema = _json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "contracts"
            / "oc-fil-execution-receipt.v1.json"
        ).read_text()
    )
    fixture = load_fixture()
    plan = _plan()
    handlers = build_handlers(fixture)
    target = plan.steps[1]
    honest = handlers[target.capability_id]
    handlers[target.capability_id] = lambda payload: replace(
        honest(payload), evidence_states=("VERIFIED",)
    )
    report = execute_dry_run(
        plan, evaluate_plan(plan), handlers, source_payload(fixture)
    )
    blocked = report.receipts[1]
    assert blocked.failure_reason == "UNDECLARED_EVIDENCE_STATE:VERIFIED"
    assert blocked.evidence_states == () and blocked.established == ()
    for receipt in report.receipts:
        jsonschema.validate(receipt.to_dict(), schema)


def test_reasoning_draft_keeps_each_claims_exact_anchor():
    fixture = load_fixture()
    report = execute_dry_run(
        _plan(),
        evaluate_plan(_plan()),
        build_handlers(fixture),
        source_payload(fixture),
    )
    assert report.succeeded
    for entry in report.final_output["entries"]:
        assert entry["evidence_anchors"]
        for anchor in entry["evidence_anchors"]:
            assert anchor["source_anchor_ids"]
            assert anchor["source_document_id"] in entry["source_document_ids"]
            assert anchor["provenance"]


# --- second independent check (exact head 60828d21) -------------------------


@pytest.mark.parametrize(
    "smuggled",
    [
        {"evidence_states": "VERIFIED"},
        {"evidenceState": "VERIFIED"},
        {"Evidence_State": "verified"},
        {"review_state": " Verified "},
        {"nested": [{"anything": ("VERIFIED",)}]},
    ],
)
def test_human_only_state_is_refused_under_any_key_or_spelling(smuggled):
    fixture = load_fixture()
    plan = _plan()
    handlers = build_handlers(fixture)
    target = plan.steps[1]
    honest = handlers[target.capability_id]
    handlers[target.capability_id] = lambda payload: replace(
        honest(payload), output={**honest(payload).output, **smuggled}
    )
    report = execute_dry_run(
        plan, evaluate_plan(plan), handlers, source_payload(fixture)
    )
    assert (
        report.receipts[1].failure_reason
        == "HUMAN_ONLY_EVIDENCE_STATE_IN_OUTPUT:VERIFIED"
    )


def test_human_only_state_in_notes_is_refused_and_never_copied():
    fixture = load_fixture()
    plan = _plan()
    handlers = build_handlers(fixture)
    target = plan.steps[1]
    honest = handlers[target.capability_id]
    handlers[target.capability_id] = lambda payload: replace(
        honest(payload), notes={"evidence_state": "VERIFIED"}
    )
    report = execute_dry_run(
        plan, evaluate_plan(plan), handlers, source_payload(fixture)
    )
    blocked = report.receipts[1]
    assert blocked.failure_reason == "HUMAN_ONLY_EVIDENCE_STATE_IN_OUTPUT:VERIFIED"
    assert blocked.notes == {}


def test_self_referencing_output_terminates_with_a_receipt():
    fixture = load_fixture()
    plan = _plan()
    handlers = build_handlers(fixture)
    target = plan.steps[1]
    loop: list = []
    loop.append(loop)
    handlers[target.capability_id] = lambda payload: HandlerResult(
        output={"loop": loop},
        established=target.effects,
        evidence_states=target.outputs[0].evidence_states[:1],
        provenance=("fixture://x",),
    )
    report = execute_dry_run(
        plan, evaluate_plan(plan), handlers, source_payload(fixture)
    )
    assert report.receipts[1].failure_reason.startswith("RESULT_NOT_RECORDABLE:")


def test_planner_finds_a_plan_that_needs_a_capability_to_recur():
    from app.functional_interaction.contracts import ProvenanceRequirement

    base = next(
        d
        for d in demo_descriptors()
        if d.capability_id == "fil.taxonomy.backbone-adaptor"
    )
    claims = base.inputs[0]
    same = PortSpec(claims.name, claims.semantic_type, claims.evidence_states)

    def make(name, *, pre=(), eff=(), keeps=True, needs_chain=True, out=same):
        return replace(
            base,
            capability_id=f"fil.test.{name}",
            outputs=(out,),
            preconditions=pre,
            effects=eff,
            provenance=ProvenanceRequirement(
                requires_upstream_chain=needs_chain, preserves_chain=keeps
            ),
        )

    registry = FunctionalRegistry(
        (
            # A must run, C (which drops the chain) must follow, and A must
            # run again before D: unplannable if a capability may not recur.
            make("a", eff=("a_done",), needs_chain=False),
            make("c", pre=("a_done",), eff=("c_done",), keeps=False),
            make("d", pre=("a_done", "c_done"), out=base.outputs[0]),
        )
    )
    source = SourceArtifact(claims.semantic_type, claims.evidence_states, ())
    plan = plan_workflow(
        registry, source=source, goal_type=base.outputs[0].semantic_type
    )
    assert plan.found
    assert [s.capability_id for s in plan.steps] == [
        "fil.test.a",
        "fil.test.c",
        "fil.test.a",
        "fil.test.d",
    ]
    assert evaluate_plan(plan).action is GovernanceAction.ALLOW_DRY_RUN


def test_micro_sign_and_greek_mu_are_both_micrometres():
    one_mm = vs.value_key(object_value=None, numeric_value=1, unit="mm")
    for unit in ("µm", "μm", "um"):
        key = vs.value_key(object_value=None, numeric_value=1000, unit=unit)
        assert vs.classify("measurement", [key, one_mm]) == vs.AGREEMENT


def test_distinct_measurements_never_share_a_display_string():
    a = vs.value_key(object_value=None, numeric_value=123.4567, unit="mm")
    b = vs.value_key(object_value=None, numeric_value=123.4568, unit="mm")
    assert vs.display(a) != vs.display(b)


def test_governance_rechecks_class_a_permissions():
    plan = _plan()
    step = plan.steps[0]
    tampered_step = replace(step)
    object.__setattr__(tampered_step, "permissions", ("read_only_research", "network"))
    tampered = replace(plan, steps=(tampered_step, *plan.steps[1:]))
    decision = evaluate_plan(tampered)
    assert decision.action is GovernanceAction.REFUSE
    assert any(r.startswith("CLASS_A_PERMISSION_NOT_SAFE:") for r in decision.reasons)


# --- third (delta) independent check (exact head 662f4481) ------------------


def test_units_are_case_sensitive_so_millimolar_is_not_millimetres():
    mm = vs.value_key(object_value=None, numeric_value=5, unit="mm")
    for unit in ("mM", "M", "\u00b5M"):
        other = vs.value_key(object_value=None, numeric_value=5, unit=unit)
        assert vs.classify("measurement", [mm, other]) == vs.INCOMMENSURABLE_UNITS


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ((1.0000001, "mm"), (1.0000002, "mm")),
        ((0.0004, "\u00b5m"), (0.0001, "\u00b5m")),
    ],
)
def test_measurements_are_exact_decimals_never_rounded_together(first, second):
    a = vs.value_key(object_value=None, numeric_value=first[0], unit=first[1])
    b = vs.value_key(object_value=None, numeric_value=second[0], unit=second[1])
    assert a != b
    assert vs.display(a) != vs.display(b)
    assert "0 mm" not in {vs.display(a), vs.display(b)}


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_measurements_are_refused(value):
    with pytest.raises(ValueError, match="NON_FINITE_MEASUREMENT"):
        vs.value_key(object_value=None, numeric_value=value, unit="mm")


@pytest.mark.parametrize("notes", [{"evidence_state": b"VERIFIED"}, {"x": {1, 2}}])
def test_unrecordable_notes_block_the_step(notes):
    fixture = load_fixture()
    plan = _plan()
    handlers = build_handlers(fixture)
    target = plan.steps[1]
    honest = handlers[target.capability_id]
    handlers[target.capability_id] = lambda payload: replace(
        honest(payload), notes=notes
    )
    report = execute_dry_run(
        plan, evaluate_plan(plan), handlers, source_payload(fixture)
    )
    assert report.receipts[1].failure_reason.startswith("RESULT_NOT_RECORDABLE:")
    assert not report.succeeded
    assert report.run_digest


@pytest.mark.parametrize(
    "lookalike",
    [
        "VERIFIED\u200b",
        "\uff36\uff25\uff32\uff29\uff26\uff29\uff25\uff24",
        " verified\u2060",
    ],
)
def test_lookalike_spellings_of_verified_are_refused(lookalike):
    fixture = load_fixture()
    plan = _plan()
    handlers = build_handlers(fixture)
    target = plan.steps[1]
    honest = handlers[target.capability_id]
    handlers[target.capability_id] = lambda payload: replace(
        honest(payload), output={**honest(payload).output, "state": lookalike}
    )
    report = execute_dry_run(
        plan, evaluate_plan(plan), handlers, source_payload(fixture)
    )
    assert (
        report.receipts[1].failure_reason
        == "HUMAN_ONLY_EVIDENCE_STATE_IN_OUTPUT:VERIFIED"
    )


def test_a_key_named_verified_is_not_mistaken_for_a_state():
    fixture = load_fixture()
    plan = _plan()
    handlers = build_handlers(fixture)
    target = plan.steps[1]
    honest = handlers[target.capability_id]
    handlers[target.capability_id] = lambda payload: replace(
        honest(payload), output={**honest(payload).output, "verified": False}
    )
    report = execute_dry_run(
        plan, evaluate_plan(plan), handlers, source_payload(fixture)
    )
    assert report.succeeded
