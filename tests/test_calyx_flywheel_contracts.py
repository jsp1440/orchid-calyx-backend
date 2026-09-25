"""Governed procedure and assertion contracts (#1138, packet 1).

The gate that matters most is the self-evidence rule. A model that can cite
itself manufactures consensus: one fluent statement supports a second, the
second a third, and confidence rises with every step while no new observation
has entered the record. Each link looks well-formed, so nothing downstream can
detect the fabrication.

The rest of these tests are about construction being the gate. If an invalid
record cannot be built, no later packet has to re-check it — and no later
packet can accidentally skip a check that lives only in a service layer.
"""

from datetime import datetime, timezone

import pytest

from app.calyx_flywheel import (
    AssertionKind,
    AssertionOrigin,
    GovernanceState,
    KnowledgeSuggestion,
    ModelIdentity,
    Procedure,
    ProcedureStep,
    ProvenanceAnchor,
    ReviewDecision,
    ReviewOutcome,
    ScientificAssertion,
    SensitiveLocalityError,
    SimulationCase,
    SimulationRun,
    StepControl,
    SupersessionRecord,
    assert_no_sensitive_locality,
)

HASH = "a" * 64
MODEL = ModelIdentity(model_id="calyx", model_version="2026.08", prompt_version="p-3")


def literature_anchor(**overrides):
    base = {
        "source_kind": "literature",
        "source_id": "lit-1",
        "content_hash": HASH,
    }
    base.update(overrides)
    return ProvenanceAnchor(**base)


def assertion(**overrides):
    base = {
        "assertion_id": "a-1",
        "kind": AssertionKind.EXTRACTED_CLAIM,
        "origin": AssertionOrigin.LITERATURE_EXTRACTED,
        "statement": "Seasonal dormancy tracks cooler thermal niches.",
        "taxonomy_version": "wcvp-2026-07",
        "provenance": (literature_anchor(),),
    }
    base.update(overrides)
    return ScientificAssertion(**base)


# ── the self-evidence rule ──────────────────────────────────────────────────


def test_an_assertion_cannot_cite_itself():
    with pytest.raises(ValueError, match="SELF_EVIDENCE_FORBIDDEN"):
        assertion(supported_by=(("a-1", AssertionOrigin.LITERATURE_EXTRACTED),))


def test_an_assertion_cannot_contradict_itself():
    with pytest.raises(ValueError, match="SELF_COUNTEREVIDENCE_FORBIDDEN"):
        assertion(counterevidence=("a-1",))


def test_a_generated_assertion_resting_only_on_generated_ones_is_rejected():
    # The loop this module exists to break: Calyx supporting Calyx, with no
    # observation anywhere underneath.
    with pytest.raises(ValueError, match="CALYX_GENERATED_ASSERTION_REQUIRES_EXTERNAL_EVIDENCE"):
        assertion(
            assertion_id="a-2",
            origin=AssertionOrigin.CALYX_GENERATED,
            kind=AssertionKind.SYNTHESIS,
            model=MODEL,
            provenance=(literature_anchor(source_kind="calyx", source_id="a-1"),),
            supported_by=(("a-1", AssertionOrigin.CALYX_GENERATED),),
        )


def test_a_generated_assertion_with_one_external_support_is_accepted():
    record = assertion(
        assertion_id="a-3",
        origin=AssertionOrigin.CALYX_GENERATED,
        kind=AssertionKind.SYNTHESIS,
        model=MODEL,
        provenance=(literature_anchor(source_kind="calyx", source_id="a-1"),),
        supported_by=(
            ("a-1", AssertionOrigin.CALYX_GENERATED),
            ("a-9", AssertionOrigin.LITERATURE_EXTRACTED),
        ),
    )
    assert record.origin is AssertionOrigin.CALYX_GENERATED


def test_a_generated_assertion_anchored_to_a_real_source_is_accepted():
    # External provenance is sufficient on its own — a generated synthesis of a
    # real paper rests on that paper.
    record = assertion(
        assertion_id="a-4",
        origin=AssertionOrigin.CALYX_GENERATED,
        kind=AssertionKind.SYNTHESIS,
        model=MODEL,
    )
    assert record.provenance[0].source_kind == "literature"


def test_a_generated_assertion_must_name_its_model():
    # A generated claim with no model or prompt version cannot be reproduced or
    # retracted by cohort, so it cannot be governed.
    with pytest.raises(ValueError, match="MODEL_IDENTITY_REQUIRED_FOR_GENERATED_ASSERTION"):
        assertion(origin=AssertionOrigin.CALYX_GENERATED, kind=AssertionKind.HYPOTHESIS)


def test_a_human_assertion_needs_no_model_identity():
    record = assertion(origin=AssertionOrigin.HUMAN_AUTHORED, kind=AssertionKind.OBSERVATION)
    assert record.model is None


# ── provenance and governance fields are required ───────────────────────────


def test_provenance_is_required():
    with pytest.raises(ValueError, match="PROVENANCE_REQUIRED"):
        assertion(provenance=())


def test_a_source_id_without_a_content_hash_is_not_provenance():
    # The named document may have changed since, and nothing would reveal it.
    for bad in ["", "not-a-hash", HASH[:63], HASH + "a", "z" * 64]:
        with pytest.raises(ValueError, match="PROVENANCE_CONTENT_HASH_REQUIRED"):
            literature_anchor(content_hash=bad)


def test_taxonomy_version_is_required():
    with pytest.raises(ValueError, match="TAXONOMY_VERSION_REQUIRED"):
        assertion(taxonomy_version="   ")


def test_confidence_outside_zero_to_one_is_rejected():
    for bad in [-0.1, 1.1, 42]:
        with pytest.raises(ValueError, match="CONFIDENCE_OUT_OF_RANGE"):
            assertion(confidence=bad)
    assert assertion(confidence=0.0).confidence == 0.0
    assert assertion(confidence=1.0).confidence == 1.0


def test_an_absent_confidence_is_allowed_and_is_not_zero():
    # Unstated confidence is not zero confidence.
    assert assertion().confidence is None


# ── nothing is publishable without approval ─────────────────────────────────


def test_assertions_default_to_provisional_and_unpublishable():
    record = assertion()
    assert record.governance_state is GovernanceState.PROVISIONAL
    assert record.publishable is False


def test_an_unapproved_assertion_cannot_be_publishable():
    with pytest.raises(ValueError, match="PUBLISHABLE_REQUIRES_APPROVAL"):
        assertion(publishable=True)
    with pytest.raises(ValueError, match="PUBLISHABLE_REQUIRES_APPROVAL"):
        assertion(publishable=True, governance_state=GovernanceState.UNDER_REVIEW)


def test_suggestions_default_to_provisional_and_unpublishable():
    suggestion = KnowledgeSuggestion(
        suggestion_id="s-1",
        assertion_id="a-1",
        proposed_change={"add_edge": "taxon->trait"},
    )
    assert suggestion.governance_state is GovernanceState.PROVISIONAL
    assert suggestion.publishable is False


def test_an_unapproved_suggestion_cannot_be_publishable():
    with pytest.raises(ValueError, match="PUBLISHABLE_REQUIRES_APPROVAL"):
        KnowledgeSuggestion(
            suggestion_id="s-2",
            assertion_id="a-1",
            proposed_change={"add_edge": "x"},
            publishable=True,
        )


def test_a_simulation_output_is_never_publishable():
    # A rehearsal that could publish is not a rehearsal.
    with pytest.raises(ValueError, match="SIMULATION_OUTPUT_NOT_PUBLISHABLE"):
        SimulationRun(run_id="r-1", case_id="c-1", publishable=True)


# ── deterministic control, not prose ────────────────────────────────────────


def test_a_step_defaults_to_no_authority():
    control = StepControl()
    assert control.may_write_graph is False
    assert control.may_terminate is False
    assert control.required_permissions == ()


def test_a_graph_write_requires_human_escalation():
    # The one action that changes shared scientific state does not proceed
    # without a human in the loop.
    with pytest.raises(ValueError, match="GRAPH_WRITE_REQUIRES_HUMAN_ESCALATION"):
        StepControl(may_write_graph=True)

    allowed = StepControl(may_write_graph=True, requires_human_escalation=True)
    assert allowed.may_write_graph is True


def test_a_branch_to_an_unknown_step_is_rejected():
    # A branch out of the procedure is not a procedure.
    with pytest.raises(ValueError, match="UNKNOWN_BRANCH_TARGET"):
        Procedure(
            procedure_id="p-1",
            version=1,
            title="Extract and reconcile",
            steps=(
                ProcedureStep(
                    step_id="s1",
                    description="Read the source",
                    control=StepControl(allowed_next_step_ids=("s-does-not-exist",)),
                ),
            ),
        )


def test_duplicate_step_ids_are_rejected():
    with pytest.raises(ValueError, match="DUPLICATE_STEP_ID"):
        Procedure(
            procedure_id="p-2",
            version=1,
            title="Duplicated",
            steps=(
                ProcedureStep(step_id="s1", description="one"),
                ProcedureStep(step_id="s1", description="two"),
            ),
        )


def test_a_procedure_needs_at_least_one_step():
    with pytest.raises(ValueError, match="PROCEDURE_REQUIRES_STEPS"):
        Procedure(procedure_id="p-3", version=1, title="Empty", steps=())


def test_a_valid_procedure_builds():
    procedure = Procedure(
        procedure_id="p-4",
        version=2,
        title="Extract and reconcile",
        steps=(
            ProcedureStep(step_id="s1", description="Read", control=StepControl(allowed_next_step_ids=("s2",))),
            ProcedureStep(step_id="s2", description="Reconcile"),
        ),
    )
    assert procedure.version == 2
    assert len(procedure.steps) == 2


# ── review outcomes ─────────────────────────────────────────────────────────


def decision(outcome, **overrides):
    base = {
        "decision_id": "d-1",
        "subject_id": "a-1",
        "outcome": outcome,
        "reviewer": "reviewer@example.com",
        "rationale": "Checked against the cited source.",
    }
    base.update(overrides)
    return ReviewDecision(**base)


@pytest.mark.parametrize(
    "outcome,expected",
    [
        (ReviewOutcome.APPROVE, GovernanceState.APPROVED),
        (ReviewOutcome.REJECT, GovernanceState.REJECTED),
        (ReviewOutcome.RETRACT, GovernanceState.RETRACTED),
    ],
)
def test_decisions_produce_their_states(outcome, expected):
    assert decision(outcome).resulting_state is expected


def test_an_abstention_leaves_the_subject_under_review():
    # A reviewer declining to decide is not a reviewer approving. Reading an
    # abstention as approval is how an unreviewed claim acquires a reviewed
    # appearance.
    assert decision(ReviewOutcome.ABSTAIN).resulting_state is GovernanceState.UNDER_REVIEW
    assert decision(ReviewOutcome.ABSTAIN).resulting_state is not GovernanceState.APPROVED


def test_supersession_requires_a_record_of_what_was_superseded():
    with pytest.raises(ValueError, match="SUPERSEDE_REQUIRES_SUPERSESSION_RECORD"):
        decision(ReviewOutcome.SUPERSEDE)

    supersede = decision(
        ReviewOutcome.SUPERSEDE,
        supersedes=SupersessionRecord(
            superseded_assertion_id="a-0",
            reason="Replaced by a larger sample",
            actor="reviewer@example.com",
        ),
    )
    assert supersede.resulting_state is GovernanceState.SUPERSEDED
    assert supersede.supersedes.superseded_assertion_id == "a-0"


def test_a_decision_without_a_rationale_is_rejected():
    # An unexplained decision cannot be audited later.
    with pytest.raises(ValueError, match="REVIEW_RATIONALE_REQUIRED"):
        decision(ReviewOutcome.APPROVE, rationale="  ")


def test_supersession_history_is_retained_on_the_assertion():
    record = assertion(
        governance_state=GovernanceState.SUPERSEDED,
        supersession_history=(
            SupersessionRecord(superseded_assertion_id="a-0", reason="superseded", actor="r"),
        ),
    )
    assert record.supersession_history[0].superseded_assertion_id == "a-0"


# ── sensitive locality ──────────────────────────────────────────────────────


def test_locality_is_rejected_at_the_top_level():
    with pytest.raises(SensitiveLocalityError, match="SENSITIVE_LOCALITY_FORBIDDEN"):
        assertion(metadata={"decimal_latitude": -23.5})


def test_locality_is_rejected_when_nested():
    # A coordinate three levels down is disclosed exactly as thoroughly as one
    # at the top.
    with pytest.raises(SensitiveLocalityError):
        assertion(metadata={"site_notes": {"observation": {"locality": "Serra do Mar"}}})


def test_locality_is_rejected_inside_a_list():
    with pytest.raises(SensitiveLocalityError):
        assertion(metadata={"records": [{"ok": 1}, {"gps": "x"}]})


def test_locality_is_rejected_in_a_provenance_locator():
    # Free-form locators are the likeliest place for a coordinate to arrive.
    with pytest.raises(SensitiveLocalityError):
        literature_anchor(locator={"coordinates": [1, 2]})


def test_locality_is_rejected_in_a_proposed_graph_change():
    with pytest.raises(SensitiveLocalityError):
        KnowledgeSuggestion(
            suggestion_id="s-3",
            assertion_id="a-1",
            proposed_change={"node": {"verbatim_locality": "Serra do Mar"}},
        )


def test_locality_is_rejected_in_simulation_inputs_and_notes():
    with pytest.raises(SensitiveLocalityError):
        SimulationCase(case_id="c-1", procedure_id="p-1", procedure_version=1, inputs={"lat": 1})
    with pytest.raises(SensitiveLocalityError):
        SimulationRun(run_id="r-2", case_id="c-1", notes={"collector": "Smith"})


def test_the_locality_check_matches_whole_keys_not_substrings():
    # `localization` and `siteswap` are not locality. A check that fired on
    # them would be disabled by the first false positive.
    assert_no_sensitive_locality({"localization": "en", "siteswap": 3, "collection_size": 4})


def test_the_locality_check_names_where_it_found_the_field():
    with pytest.raises(SensitiveLocalityError, match=r"outer\.inner\.locality"):
        assert_no_sensitive_locality({"outer": {"inner": {"locality": "x"}}})


def test_the_locality_check_does_not_scan_string_contents():
    # Inspecting values would guess whether a number is a latitude, producing
    # false positives on real measurements. The contract is that protected
    # locality travels under a known field name.
    assert_no_sensitive_locality({"statement": "Collected near a locality in Brazil at -23.5"})


# ── contract identity ───────────────────────────────────────────────────────


def test_records_carry_a_contract_version():
    assert assertion().contract_version == "calyx-flywheel/1"
    assert (
        KnowledgeSuggestion(
            suggestion_id="s-4", assertion_id="a-1", proposed_change={"x": 1}
        ).contract_version
        == "calyx-flywheel/1"
    )


def test_created_at_is_timezone_aware():
    # A naive timestamp cannot be compared across systems without guessing.
    assert assertion().created_at.tzinfo is not None
    assert assertion(created_at=datetime(2026, 8, 23, tzinfo=timezone.utc)).created_at.year == 2026
