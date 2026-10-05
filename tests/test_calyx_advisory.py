from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.calyx_advisory import disagreement, pipeline
from app.calyx_advisory.contract import (
    CONTRACT,
    FINDING_KINDS,
    PROHIBITED_ACTIONS,
    ContractViolation,
    validate_advisory,
)
from app.calyx_advisory.discovery_adapter import ROUTES, to_candidates
from app.calyx_advisory.evaluator import evaluate
from app.calyx_advisory.presentations import (
    build_presentations,
    core_fingerprint,
    verify_presentation,
)
from app.calyx_advisory.registry import COMPETENCIES, covered_kinds

FIXTURE = Path(__file__).parent / "fixtures" / "calyx_advisory" / "contested_pollination.json"


@pytest.fixture()
def artifact():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture()
def claim(artifact):
    return artifact["claims"][0]


def _kinds(advisory):
    return [f["kind"] for f in advisory["findings"]]


# ---- registry & contract ---------------------------------------------------


def test_registry_covers_every_advisory_kind_except_no_action():
    assert covered_kinds() == set(FINDING_KINDS) - {"no_action"}
    assert {c.key for c in COMPETENCIES} >= {
        "science-education", "curriculum-instructional-design", "teaching-modalities",
        "learning-progression-assessment", "accessibility", "scientific-communication",
        "information-architecture", "web-interaction-design",
    }


def test_advisory_validates_and_states_its_prohibitions(artifact):
    advisory = evaluate(artifact)
    validate_advisory(advisory)
    assert advisory["contract"] == CONTRACT == "calyx_advisory_contract.v1"
    assert set(advisory["prohibited_actions"]) == set(PROHIBITED_ACTIONS)
    assert all(f["scientific_effect"] == "none" for f in advisory["findings"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda a: a.update(contract="other"),
        lambda a: a["prohibited_actions"].remove("disclose_protected_locality"),
        lambda a: a["findings"][0].update(scientific_effect="reword_claim"),
        lambda a: a["findings"][0].update(kind="rewrite_evidence"),
        lambda a: a["findings"][0].update(evidence=[]),
        lambda a: a.update(extra={"latitude": 1.0}),
    ],
)
def test_contract_rejects_a_breaching_advisory(artifact, mutate):
    advisory = evaluate(artifact)
    mutate(advisory)
    with pytest.raises(ContractViolation):
        validate_advisory(advisory)


# ---- evaluator ----------------------------------------------------------------


def test_fixture_yields_every_gap_family_deterministically(artifact):
    first, second = evaluate(artifact), evaluate(copy.deepcopy(artifact))
    assert first == second
    kinds = set(_kinds(first))
    assert {"educational_gap", "accessibility_gap", "ux_gap", "curriculum_gap",
            "teaching_opportunity"} <= kinds
    educational = next(f for f in first["findings"] if f["kind"] == "educational_gap")
    assert educational["severity"] == "high"
    assert "missing_mechanisms:mech-oviposition-mimicry" in educational["evidence"]
    assert "Restore" in educational["recommendation"]


def test_settled_claim_with_complete_surfaces_is_no_action(artifact):
    settled = copy.deepcopy(artifact)
    settled["claims"][0]["evidence_state"] = "established"
    settled["surfaces"][0].update(
        has_media=False, items_shown=3, reading_level="grade-8", progressive_disclosure=True
    )
    advisory = evaluate(settled)
    assert _kinds(advisory) == ["no_action"]
    assert to_candidates(advisory, settled) == []


def test_protected_locality_in_an_artifact_is_refused(artifact):
    artifact["claims"][0]["provenance"][0]["coordinates"] = [0, 0]
    with pytest.raises(ContractViolation, match="ARTIFACT_CONTAINS_LOCALITY"):
        evaluate(artifact)


def test_evaluation_does_not_mutate_the_artifact(artifact):
    before = copy.deepcopy(artifact)
    evaluate(artifact)
    assert artifact == before


# ---- one science, three experiences --------------------------------------------


def test_same_evidence_yields_three_presentations_with_one_scientific_core(claim):
    tiers = build_presentations(claim)
    assert set(tiers) == {"beginner", "inquiry", "advanced"}
    assert len({t["core_fingerprint"] for t in tiers.values()}) == 1
    assert tiers["beginner"]["core_fingerprint"] == core_fingerprint(claim)
    for tier in tiers.values():
        verify_presentation(claim, tier)
        assert tier["evidence_state"] == "contested"
        assert tier["mechanism_ids"] == ["mech-food-deception", "mech-oviposition-mimicry"]
        assert tier["uncertainty"] == claim["uncertainty"]["statement"]
    # The experiences differ in structure, not in science.
    assert {t["structure"] for t in tiers.values()} == {
        "compare_hypotheses_side_by_side", "predict_observe_compare", "evidence_matrix"}
    assert tiers["beginner"]["headline"].startswith("Scientists have 2 explanations")
    assert all(not task["open_question"] for task in tiers["inquiry"]["body"])
    assert tiers["advanced"]["uncertainty_reason"] == claim["uncertainty"]["reason"]
    assert [m["evidence_refs"] for m in tiers["advanced"]["body"]] == [
        ["fixture-ev-1", "fixture-ev-2"], ["fixture-ev-3"]]


def test_missing_distinguishing_observation_is_stated_as_open_not_invented(claim):
    claim = copy.deepcopy(claim)
    del claim["mechanisms"][1]["distinguishing_observation"]
    task = build_presentations(claim)["inquiry"]["body"][1]
    assert task["open_question"] is True
    assert "open question" in task["task"]


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda t: t.update(mechanism_ids=["mech-food-deception"]), "QUALIFICATION_REMOVED:mechanism"),
        (lambda t: t.update(uncertainty=None), "QUALIFICATION_REMOVED:uncertainty"),
        (lambda t: t.update(evidence_state="established"), "QUALIFICATION_REMOVED:evidence_state"),
        (lambda t: t.update(core_fingerprint="0" * 64), "PRESENTATION_CORE_CHANGED"),
    ],
)
def test_a_presentation_that_removes_a_qualification_is_rejected(claim, edit, message):
    tier = build_presentations(claim)["beginner"]
    edit(tier)
    with pytest.raises(ContractViolation, match=message):
        verify_presentation(claim, tier)


def test_uncertain_claim_without_an_uncertainty_statement_is_refused(claim):
    claim = copy.deepcopy(claim)
    claim["uncertainty"] = None
    with pytest.raises(ContractViolation, match="UNCERTAIN_CLAIM_WITHOUT"):
        build_presentations(claim)


# ---- Brain <-> Calyx disagreement ---------------------------------------------------


def _brain(claim):
    return {
        "claim_id": claim["id"],
        "position": "Evidence supports competing mechanisms and they cannot currently be resolved.",
        "evidence_state": claim["evidence_state"],
        "mechanism_ids": [m["id"] for m in claim["mechanisms"]],
        "uncertainty": claim["uncertainty"]["statement"],
    }


def _calyx(claim, change):
    return {
        "claim_id": claim["id"],
        "concern": "The unresolved disagreement is difficult for introductory learners.",
        "audience": "beginner",
        "requested_change": change,
    }


@pytest.mark.parametrize("change", sorted(disagreement.QUALIFICATION_REMOVING))
def test_removing_a_qualification_is_rejected_and_becomes_a_design_mission(claim, change):
    record = disagreement.resolve(_brain(claim), _calyx(claim, change))
    assert record["decision"] == "rejected_qualification_removal"
    assert record["authority"] == "brain"
    assert record["scientific_conclusion_unchanged"] is True
    assert record["brain_position"] == _brain(claim)
    mission = record["design_mission"]
    assert mission["bounded"] is True
    assert mission["must_preserve"]["mechanism_ids"] == ["mech-food-deception", "mech-oviposition-mimicry"]
    assert mission["must_preserve"]["uncertainty"] == claim["uncertainty"]["statement"]
    assert "remove_mechanism" in mission["must_not"]


@pytest.mark.parametrize("change", sorted(disagreement.PRESENTATION_CHANGES))
def test_presentation_only_changes_are_accepted(claim, change):
    record = disagreement.resolve(_brain(claim), _calyx(claim, change))
    assert record["decision"] == "accepted_presentation_change"
    assert record["design_mission"] is None
    assert record["scientific_conclusion_unchanged"] is True


def test_unknown_requests_fail_closed_to_brain_review(claim):
    record = disagreement.resolve(_brain(claim), _calyx(claim, "make_it_shorter_somehow"))
    assert record["decision"] == "needs_brain_review"


def test_disagreement_requires_matching_claims_and_a_brain_position(claim):
    other = _calyx(claim, "add_scaffold") | {"claim_id": "other"}
    with pytest.raises(ContractViolation, match="MISMATCH"):
        disagreement.resolve(_brain(claim), other)
    with pytest.raises(ContractViolation, match="BRAIN_POSITION_REQUIRES_POSITION"):
        disagreement.resolve(_brain(claim) | {"position": ""}, _calyx(claim, "add_scaffold"))


# ---- Improvement-Discovery adapter and acceptance pipeline ---------------------------------


def test_candidates_are_bounded_routed_and_inherit_discovery_invariants(artifact):
    advisory = evaluate(artifact)
    candidates = to_candidates(advisory, artifact)
    assert 0 < len(candidates) <= 5
    assert {c["target_module"] for c in candidates} <= set(ROUTES.values())
    for c in candidates:
        assert c["schema"] == "oc.improvement-candidate.v1"
        assert c["requires_human_review"] is True
        assert c["may_modify_governance"] is False
        assert c["may_promote_hypothesis"] is False
        assert c["may_activate_scientific_conclusion"] is False
        assert c["provenance"]["artifact_checksum"] == advisory["artifact_checksum"]
        assert "no-protected-locality" in c["safety_gates"]
        assert c["acceptance_criteria"] and c["evidence"]
    assert len({c["fingerprint"] for c in candidates}) == len(candidates)
    routes = {c["finding_kind"]: c["target_module"] for c in candidates}
    assert routes["accessibility_gap"] == routes["ux_gap"] == "frontend-ux"
    assert routes["educational_gap"] == "university-education"


def test_candidates_are_deduplicated_against_known_fingerprints_and_capped(artifact):
    advisory = evaluate(artifact)
    full = to_candidates(advisory, artifact)
    known = frozenset(c["fingerprint"] for c in full)
    assert to_candidates(advisory, artifact, known_fingerprints=known) == []
    assert len(to_candidates(advisory, artifact, max_candidates=2)) == 2


def test_adapter_rejects_an_advisory_for_a_different_artifact(artifact):
    advisory = evaluate(artifact)
    changed = copy.deepcopy(artifact)
    changed["title"] = "edited"
    with pytest.raises(ContractViolation, match="ADVISORY_ARTIFACT_MISMATCH"):
        to_candidates(advisory, changed)


def test_acceptance_pipeline_end_to_end_is_provider_free_and_honest(artifact):
    result = pipeline.run(artifact)
    receipt = result["receipt"]
    assert receipt["passed"] is True
    assert all(receipt["checks"].values())
    assert receipt["independent"] is False  # a maker-side self-check, not certification
    assert receipt["routes"] == ["frontend-ux", "university-education"]
    assert receipt["candidate_fingerprints"] == [c["fingerprint"] for c in result["candidates"]]
    # Re-running is idempotent: same receipt.
    assert pipeline.run(copy.deepcopy(artifact))["receipt"] == receipt
    # Second pass with the fingerprints already known proposes nothing new.
    again = pipeline.run(artifact, known_fingerprints=frozenset(receipt["candidate_fingerprints"]))
    assert again["candidates"] == []
