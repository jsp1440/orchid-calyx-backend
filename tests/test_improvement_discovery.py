"""Proofs for Improvement Discovery.

When the reasoning map cannot settle a question, failing is the wrong response
and guessing is worse. These tests pin that the shortfall is *classified* — the
kind determines who can act on it — and that a candidate can never approve
itself, rewrite governance, or promote what it was derived from.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.cognitive_integration.executor import execute
from app.cognitive_integration.improvement_discovery import (
    NOTHING_BLOCKED,
    Deficiency,
    ImprovementCandidate,
    classify,
    discover,
    to_report,
)
from app.main import app


@pytest.fixture(scope="module")
def report() -> dict:
    return to_report(execute())


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def candidate(**overrides) -> ImprovementCandidate:
    base = {
        "deficiency": Deficiency.MISSING_EVIDENCE,
        "statement": "No observation supports the claim.",
        "why_it_matters": "The claim rests on literature alone.",
        "bounded_next_step": "Record what observation would close it.",
        "blocks_question": "What pollinates the bee orchid?",
    }
    base.update(overrides)
    return ImprovementCandidate(**base)


# ---------------------------------------------------------------------------
# It classifies rather than reporting one undifferentiated failure
# ---------------------------------------------------------------------------


def test_candidates_are_derived_from_the_real_reasoning_map(report):
    assert report["candidate_count"] > 0
    assert set(report["by_deficiency"]) >= {
        "missing_evidence",
        "missing_ontology_term",
        "missing_reasoning_operation",
    }


def test_a_conflict_is_a_missing_operation_not_missing_evidence(report):
    """The distinction that matters most.

    Two reports that disagree are not an absence of evidence — evidence exists on
    both sides. What is missing is an operation that would decide between them,
    and calling that a data gap would send the work to the wrong person.
    """
    operations = report["by_deficiency"]["missing_reasoning_operation"]
    assert len(operations) == 1
    assert "not an absence of evidence" in operations[0]["why_it_matters"]
    assert "contested" in operations[0]["why_it_matters"]


def test_a_rank_shortfall_is_an_ontology_problem_not_a_data_one(report):
    ontology = report["by_deficiency"]["missing_ontology_term"]
    assert "genus" in ontology[0]["statement"]
    assert "rank the question needs" in ontology[0]["bounded_next_step"]


def test_an_unavailable_optional_capability_is_recorded_but_blocks_nothing(report):
    capability = report["by_deficiency"]["missing_capability"][0]
    assert capability["blocks_question"] == NOTHING_BLOCKED
    assert "blocks nothing scientific" in capability["why_it_matters"]


def test_a_resolved_contradiction_produces_no_operation_candidate():
    """A disagreement explained by scope is not a deficiency."""
    reasoning = execute()
    reasoning["contradictions"] = [
        {**reasoning["contradictions"][0], "resolution": "resolved_by_scope"}
    ]
    kinds = {c.deficiency for c in discover(reasoning)}
    assert Deficiency.MISSING_REASONING_OPERATION not in kinds


def test_a_map_with_nothing_missing_produces_no_candidates():
    empty = {"question": "q", "evidence_gaps": [], "contradictions": [], "execution": {}}
    assert discover(empty) == []


def test_an_absent_evidence_class_is_an_ingestion_problem_not_a_data_one(report):
    """This kind was unreachable: the broader observation pattern matched first.

    The docstring promised most-specific-first ordering and the code did not
    deliver it, so a pipeline gap was reported as a shortage of sources.
    """
    ingestion = report["by_deficiency"]["missing_ingestion"]
    assert len(ingestion) == 1
    assert "pipeline question" in ingestion[0]["why_it_matters"]
    assert classify("literature and aggregated records only")[0] is Deficiency.MISSING_INGESTION


def test_each_gap_the_executor_emits_classifies_as_the_kind_it_is():
    """Reachability, asserted against sentences the system actually produces.

    The test this replaced fed each pattern's own *source text* in as if it were
    a gap statement, compared sets of kinds rather than per-sentence outcomes,
    and fell back to ``MISSING_EVIDENCE`` — itself a declared kind — so a
    shadowed rule could never show up as unreachable. It passed with the
    ``MISSING_INGESTION`` bug fully restored: ``"literature and aggregated
    records only"`` is not shadowed, while the real sentence containing it,
    ``"No local observation supports any retrieved claim; the evidence is
    literature and aggregated records only."``, is.

    So the probes here are the executor's real output, and each is pinned to one
    kind rather than to a set.
    """
    expected = {
        "Eucera (solitary bees) is identified to genus, not species, in the "
        "retrieved evidence.": Deficiency.MISSING_ONTOLOGY_TERM,
        "no source quantifies the contribution of either strategy":
            Deficiency.MISSING_EVIDENCE,
        "No local observation supports any retrieved claim; the evidence is "
        "literature and aggregated records only.": Deficiency.MISSING_INGESTION,
        "no population-level pollination observation is held":
            Deficiency.MISSING_EVIDENCE,
    }
    emitted = set(execute()["evidence_gaps"])
    assert set(expected) <= emitted, (
        "these probes must be sentences the executor emits, not invented ones; "
        f"missing from output: {sorted(set(expected) - emitted)}"
    )
    for sentence, kind in expected.items():
        assert classify(sentence)[0] is kind, (
            f"{sentence!r} classified as {classify(sentence)[0]}, expected {kind}"
        )


def test_the_more_specific_rule_wins_where_two_rules_both_match():
    """The ordering invariant, stated as the overlap it exists to settle.

    Both the ingestion rule and the broader observation rule match this
    sentence. Whichever is consulted first decides, and only one of the two
    answers sends anyone to do useful work: an absent evidence class is a
    pipeline question, while "find more sources" is advice to look harder for
    records that were never ingested.
    """
    from app.cognitive_integration.improvement_discovery import _CLASSIFIERS

    sentence = (
        "No local observation supports any retrieved claim; the evidence is "
        "literature and aggregated records only."
    )
    matching = [kind for pattern, kind, _ in _CLASSIFIERS if pattern.search(sentence)]
    assert len(matching) > 1, "this sentence must be genuinely ambiguous to be a test"
    assert Deficiency.MISSING_INGESTION in matching
    assert Deficiency.MISSING_EVIDENCE in matching
    assert classify(sentence)[0] is Deficiency.MISSING_INGESTION


def test_no_classifier_rule_is_shadowed_into_dead_code():
    """Every rule must be the winner for at least one string it matches.

    A rule an earlier one always beats is dead code wearing a rule's clothes,
    and the docstring above ``_CLASSIFIERS`` promises most-specific-first.
    """
    from app.cognitive_integration.improvement_discovery import _CLASSIFIERS

    emitted = list(execute()["evidence_gaps"])
    for index, (pattern, kind, _) in enumerate(_CLASSIFIERS):
        matched = [g for g in emitted if pattern.search(g)]
        assert matched, (
            f"rule {index} ({pattern.pattern!r}) matches nothing the executor emits, "
            "so its reachability cannot be established from real output"
        )
        assert any(classify(g)[0] is kind for g in matched), (
            f"rule {index} ({pattern.pattern!r} -> {kind}) never wins: every gap it "
            "matches is claimed by an earlier rule"
        )


def test_classification_falls_back_to_the_least_actionable_kind():
    """A wrong specific kind routes work to the wrong person; a vague one asks someone to look."""
    kind, why = classify("something the system did not anticipate")
    assert kind is Deficiency.MISSING_EVIDENCE
    assert "not specific enough to route" in why


def test_every_candidate_names_a_bounded_next_step(report):
    for items in report["by_deficiency"].values():
        for item in items:
            assert item["bounded_next_step"].strip()
            assert item["statement"].strip()
            assert item["why_it_matters"].strip()


# ---------------------------------------------------------------------------
# It cannot grant itself authority
# ---------------------------------------------------------------------------


def test_a_candidate_may_not_mark_itself_reviewed():
    with pytest.raises(ValueError, match="DISCOVERY_REVIEW_INVARIANT"):
        candidate(requires_human_review=False)


@pytest.mark.parametrize(
    "flag",
    ["may_modify_governance", "may_promote_hypothesis", "may_activate_scientific_conclusion"],
)
def test_a_candidate_may_not_claim_scientific_or_governance_authority(flag):
    with pytest.raises(ValueError, match="DISCOVERY_AUTHORITY_INVARIANT"):
        candidate(**{flag: True})


def test_the_report_states_its_limits_rather_than_implying_them(report):
    authority = report["authority"]
    assert authority["requires_human_review"] is True
    assert authority["may_modify_governance"] is False
    assert authority["may_promote_hypothesis"] is False
    assert authority["may_activate_scientific_conclusion"] is False


def test_every_derived_candidate_carries_the_invariants(report):
    for items in report["by_deficiency"].values():
        for item in items:
            assert item["requires_human_review"] is True
            assert item["may_modify_governance"] is False
            assert item["may_promote_hypothesis"] is False
            assert item["may_activate_scientific_conclusion"] is False


def test_discovery_does_not_alter_the_map_it_reads():
    before = execute()
    snapshot = str(before)
    discover(before)
    assert str(before) == snapshot


# ---------------------------------------------------------------------------
# Over HTTP
# ---------------------------------------------------------------------------


def test_the_candidates_are_served(client):
    response = client.get("/api/cognitive-integration/improvement-candidates")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["candidate_count"] > 0
    assert body["authority"]["may_activate_scientific_conclusion"] is False


def test_an_unsupported_question_is_refused(client):
    response = client.get(
        "/api/cognitive-integration/improvement-candidates",
        params={"question": "unrelated"},
    )
    assert response.status_code == 422
