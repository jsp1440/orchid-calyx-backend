from datetime import datetime, timezone

import pytest

from app.canonical_brain.priority_batch_seven import (
    AgentCapacity,
    CharacterAssessment,
    ContractTestCase,
    ExpeditionSite,
    GlossaryUsageEvent,
    ManuscriptSectionPlan,
    PollinatorObservationCandidate,
    TreatmentEvent,
    build_manuscript_plan,
    build_review_packet,
    explain_identification_uncertainty,
    propose_supersession,
    rank_expedition_sites,
    rank_pollinator_candidates,
    run_contract_tests,
    summarize_capacity,
    summarize_glossary_usage,
)

NOW = datetime(2026, 8, 6, 20, 0, tzinfo=timezone.utc)


def test_glossary_usage_is_aggregated_without_user_identity():
    summary = summarize_glossary_usage([
        GlossaryUsageEvent(concept_id="velamen", action="popover_open", occurred_at=NOW),
        GlossaryUsageEvent(concept_id="velamen", action="media_open", occurred_at=NOW),
    ])
    assert summary[0].total_events == 2
    assert summary[0].action_counts == {"media_open": 1, "popover_open": 1}


def test_expedition_ranking_is_deterministic_and_candidate_only():
    sites = [
        ExpeditionSite(site_id="b", conservation_priority=.8, sampling_gap=.9, access_feasibility=.3, evidence_ids=["e2"]),
        ExpeditionSite(site_id="a", conservation_priority=.9, sampling_gap=.7, access_feasibility=.8, evidence_ids=["e1"]),
    ]
    ranked = rank_expedition_sites(sites)
    assert [item.site_id for item in ranked] == ["a", "b"]
    assert all(item.status == "candidate" for item in ranked)


def test_review_packet_is_repeatable():
    first = build_review_packet("p1", ["h2", "h1"], ["e1"], ["a1"], ["scientific"])
    second = build_review_packet("p1", ["h1", "h2"], ["e1"], ["a1"], ["scientific"])
    assert first.checksum == second.checksum


def test_treatment_closure_enforces_chronology_and_terminal_state():
    event = TreatmentEvent(treatment_id="t1", specimen_id="s1", diagnosis="rot", treatment="remove tissue", started_at=NOW)
    closed = event.close(datetime(2026, 8, 7, tzinfo=timezone.utc), "resolved")
    assert closed.outcome == "resolved"
    with pytest.raises(ValueError):
        closed.close(datetime(2026, 8, 8, tzinfo=timezone.utc), "resolved")


def test_uncertainty_explanation_separates_missing_conflicting_and_low_confidence():
    explanation = explain_identification_uncertainty([
        CharacterAssessment(character_id="c1", observed_state="red", expected_state="red", confidence=.9),
        CharacterAssessment(character_id="c2", observed_state="red", expected_state="white", confidence=.8),
        CharacterAssessment(character_id="c3", observed_state=None, expected_state="round", confidence=.4),
    ])
    assert explanation.matched == ["c1"]
    assert explanation.conflicting == ["c2"]
    assert explanation.missing == ["c3"]
    assert explanation.low_confidence == ["c3"]


def test_pollinator_candidates_are_ranked_without_finalizing_interaction():
    ranked = rank_pollinator_candidates([
        PollinatorObservationCandidate(observation_id="o1", image_id="i", orchid_taxon_id="orchid", interaction_type="approach", confidence=.4, evidence_region_id="r1"),
        PollinatorObservationCandidate(observation_id="o2", image_id="i", orchid_taxon_id="orchid", interaction_type="contact", confidence=.9, evidence_region_id="r2"),
    ])
    assert ranked[0].observation_id == "o2"
    assert ranked[0].status == "candidate"


def test_manuscript_plan_rejects_duplicate_sections_and_disables_submission():
    section = ManuscriptSectionPlan(section_id="intro", title="Introduction", required_evidence_classes=["literature"], source_object_ids=["obj1"])
    with pytest.raises(ValueError):
        build_manuscript_plan("m1", [section, section])
    plan = build_manuscript_plan("m1", [section])
    assert plan.submission_enabled is False


def test_contract_tests_report_expected_and_unexpected_results():
    cases = [
        ContractTestCase(test_id="t1", contract_id="c1", payload={"ok": True}, expected_valid=True),
        ContractTestCase(test_id="t2", contract_id="c1", payload={"ok": False}, expected_valid=True),
    ]
    results = run_contract_tests(cases, lambda _contract, payload: payload["ok"])
    assert [item.passed for item in results] == [True, False]


def test_capacity_summary_reports_saturation_and_architecture_availability():
    summary = summarize_capacity([
        AgentCapacity(agent_id="a1", architecture_ids=["atlas"], capacity_units=2, active_units=2),
        AgentCapacity(agent_id="a2", architecture_ids=["atlas", "brain"], capacity_units=3, active_units=1),
    ])
    assert summary.available_units == 2
    assert summary.saturated_agent_ids == ["a1"]
    assert summary.available_by_architecture == {"atlas": 2, "brain": 2}


def test_supersession_rejects_self_reference_and_is_stable():
    with pytest.raises(ValueError):
        propose_supersession("obj1", "obj1", "replace", ["e1"])
    first = propose_supersession("old", "new", "new architecture approved", ["e2", "e1"])
    second = propose_supersession("old", "new", "new architecture approved", ["e1", "e2"])
    assert first.proposal_id == second.proposal_id
    assert first.status == "proposed"
