from dataclasses import replace

import pytest

from app.evals.improvement_discovery import (
    ImprovementDiscoveryEngine,
    ImprovementEligibility,
    ImprovementHypothesis,
    ImprovementSignal,
    ImprovementSignalSource,
    PriorImprovementOutcome,
    material_change_fingerprint,
)
from app.evals.models import MeasurementState, StrategyDecisionState


def signal(*, material="m1", risk="low", value=0.72):
    return ImprovementSignal(
        signal_id="sig-1",
        version="1",
        source=ImprovementSignalSource.EVALUATION,
        task_class_id="literature-reconciliation",
        risk_class=risk,
        observation="baseline recall is below the desired threshold",
        evidence_refs=("issue:#1396", "eval:fixture-001"),
        material_fingerprint=material,
        measured_metric="recall",
        measured_value=value,
        desired_direction="increase",
    )


def hypothesis(sig: ImprovementSignal, *, owner=False):
    return ImprovementHypothesis(
        hypothesis_id="retrieve-before-synthesis",
        version="1",
        signal_fingerprint=sig.fingerprint,
        task_class_id=sig.task_class_id,
        risk_class=sig.risk_class,
        proposed_change="Add bounded retrieval before synthesis for this task class.",
        expected_effect="Increase recall without reducing mandatory scientific gates.",
        primary_metric="recall",
        baseline_strategy_fingerprint="baseline-fp",
        candidate_strategy_ref="candidate:retrieve-before-synthesis:v1",
        rollback_strategy_fingerprint="baseline-fp",
        evaluation_plan=(
            "Run baseline and candidate on the same frozen provider-free fixtures.",
            "Apply mandatory scientific/safety gates before score comparison.",
            "Promote only through OC-EVALS if measured benefit is material.",
        ),
        evidence_refs=sig.evidence_refs,
        material_fingerprint=sig.material_fingerprint,
        owner_approval_required=owner,
    )


def test_provider_free_discovery_is_deterministic():
    first = signal()
    second = signal()
    assert first.fingerprint == second.fingerprint
    assert hypothesis(first).fingerprint == hypothesis(second).fingerprint


def test_no_benefit_is_suppressed_until_material_change():
    engine = ImprovementDiscoveryEngine()
    sig = signal(material="m1")
    hyp = hypothesis(sig)
    prior = PriorImprovementOutcome(
        hypothesis_fingerprint=hyp.fingerprint,
        signal_material_fingerprint="m1",
        decision_state=StrategyDecisionState.KEEP_BASELINE,
    )
    assert (
        engine.classify_eligibility(sig, hyp, [prior])
        == ImprovementEligibility.SUPPRESSED_NO_BENEFIT
    )

    changed = signal(material="m2", value=0.61)
    changed_hyp = hypothesis(changed)
    assert (
        engine.classify_eligibility(changed, changed_hyp, [prior])
        == ImprovementEligibility.ELIGIBLE
    )


def test_queue_packet_requires_evals_and_never_auto_promotes():
    engine = ImprovementDiscoveryEngine()
    sig = signal()
    hyp = hypothesis(sig)
    packet = engine.build_queue_packet(sig, hyp)

    assert packet.labels == ("oc-queued", "oc-p1")
    assert packet.requires_evaluation is True
    assert packet.auto_promotable is False
    assert (
        "OC-EVALS baseline/candidate evidence is required before promotion"
        in packet.body
    )
    assert "rollback strategy: `baseline-fp`" in packet.body
    assert f"OC-QUEUE-CAPABILITY: {packet.capability}" in packet.body
    assert hyp.candidate_material_fingerprint in packet.capability


def test_high_risk_hypothesis_is_owner_gated_not_auto_promotable():
    engine = ImprovementDiscoveryEngine()
    sig = signal(risk="high")
    hyp = hypothesis(sig)

    assert (
        engine.classify_eligibility(sig, hyp) == ImprovementEligibility.REQUIRES_OWNER
    )
    packet = engine.build_queue_packet(sig, hyp)
    assert packet.labels == ("oc-blocked", "oc-p1")
    assert "owner approval required: `true`" in packet.body
    assert packet.auto_promotable is False


def test_unknown_measurement_is_truthful_and_not_treated_as_zero():
    engine = ImprovementDiscoveryEngine()
    sig = signal(value=None)
    hyp = hypothesis(sig)
    assert engine.classify_eligibility(sig, hyp) == ImprovementEligibility.UNMEASURED


def test_scientific_memory_summary_is_compact_evidence_not_reasoning():
    engine = ImprovementDiscoveryEngine()
    sig = signal()
    hyp = hypothesis(sig)
    summary = engine.scientific_memory_summary(
        sig, hyp, ImprovementEligibility.ELIGIBLE
    )

    assert summary["schema"] == "oc.improvement-discovery-memory.v1"
    assert summary["rollback_strategy_fingerprint"] == "baseline-fp"
    assert "observation" not in summary
    assert "proposed_change" not in summary


def test_material_change_fingerprint_changes_with_material_payload():
    a = material_change_fingerprint({"eval_version": "1", "score": 0.7})
    b = material_change_fingerprint({"eval_version": "2", "score": 0.7})
    assert a != b


@pytest.mark.parametrize("state", list(StrategyDecisionState))
def test_queue_admission_enforces_prior_outcomes(state):
    engine = ImprovementDiscoveryEngine()
    sig = signal()
    hyp = hypothesis(sig)
    outcome = PriorImprovementOutcome(hyp.fingerprint, sig.material_fingerprint, state)
    with pytest.raises(ValueError, match="suppressed"):
        engine.build_queue_packet(sig, hyp, prior_outcomes=[outcome])


def test_editorial_changes_do_not_evade_no_benefit_suppression():
    engine = ImprovementDiscoveryEngine()
    sig = signal()
    hyp = hypothesis(sig)
    outcome = PriorImprovementOutcome(
        hyp.fingerprint,
        sig.material_fingerprint,
        StrategyDecisionState.KEEP_BASELINE,
        hyp.candidate_material_fingerprint,
    )
    reworded = replace(hyp, proposed_change="Same candidate, different description.")
    assert reworded.fingerprint != hyp.fingerprint
    with pytest.raises(ValueError, match="suppressed"):
        engine.build_queue_packet(sig, reworded, prior_outcomes=[outcome])
    changed_sig = signal(material="new-evaluator-version")
    changed = hypothesis(changed_sig)
    assert engine.build_queue_packet(changed_sig, changed, prior_outcomes=[outcome])


def test_capability_identity_separates_candidates_and_preserves_editorial_replay():
    engine = ImprovementDiscoveryEngine()
    sig = signal()
    hyp = hypothesis(sig)
    first = engine.build_queue_packet(sig, hyp)
    reworded = engine.build_queue_packet(
        sig, replace(hyp, expected_effect="Clearer wording.")
    )
    other = engine.build_queue_packet(
        sig, replace(hyp, candidate_strategy_ref="candidate:other:v1")
    )
    assert first.capability == reworded.capability
    assert first.capability != other.capability


@pytest.mark.parametrize(
    "field,value",
    [
        ("signal_fingerprint", "stale"),
        ("material_fingerprint", "stale"),
        ("task_class_id", "other"),
        ("risk_class", "high"),
        ("rollback_strategy_fingerprint", ""),
        ("rollback_strategy_fingerprint", "unrelated"),
        ("baseline_strategy_fingerprint", ""),
        ("evaluation_plan", ()),
        ("evidence_refs", ()),
    ],
)
def test_queue_admission_rejects_unbound_or_incomplete_hypotheses(field, value):
    sig = signal()
    with pytest.raises(ValueError):
        ImprovementDiscoveryEngine().build_queue_packet(
            sig, replace(hypothesis(sig), **{field: value})
        )


def test_unknown_unavailable_and_measured_zero_remain_distinct():
    engine = ImprovementDiscoveryEngine()
    missing = signal(value=None)
    unavailable = replace(missing, measurement_state=MeasurementState.UNAVAILABLE)
    zero = signal(value=0)
    states = []
    for sig in (missing, unavailable, zero):
        hyp = hypothesis(sig)
        summary = engine.scientific_memory_summary(
            sig, hyp, engine.classify_eligibility(sig, hyp)
        )
        states.append(summary["measurement"])
    assert states == [
        {"state": "UNKNOWN", "value": None},
        {"state": "UNAVAILABLE", "value": None},
        {"state": "MEASURED", "value": 0},
    ]
    assert missing.fingerprint != unavailable.fingerprint


@pytest.mark.parametrize("value", [float("inf"), float("nan"), True])
def test_invalid_measured_values_fail_closed(value):
    with pytest.raises(ValueError):
        signal(value=value)


def test_version_is_part_of_signal_identity():
    sig = signal()
    assert replace(sig, version="2").fingerprint != sig.fingerprint
