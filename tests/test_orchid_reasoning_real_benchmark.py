"""Contract tests for the real-question benchmark machinery.

Every case, source and review below is in-test data about the fictional genus
*Exemplaria*; it exercises the validator and scorer only and is never written
to ``benchmarks/orchid_reasoning_real``.
"""

import copy
from hashlib import sha256

import pytest

from app.graph_grounded_reasoning.real_benchmark import (
    BENCHMARK_VERSION,
    DISAGREEMENT,
    INSUFFICIENT_REVIEW,
    SCORABLE,
    load_suite,
    model_transmission_permitted,
    score_suite,
    to_evaluation_case,
    validate_suite,
)


def source(doc, rights="OPEN_LICENSE", excerpt=None):
    record = {
        "document_id": doc,
        "rights_state": rights,
        "citation": {"title": f"Synthetic {doc}", "author_or_creator": "Test", "publication_year": 2020,
                     "url_or_identifier": f"test:{doc}"},
        "locator": {"page": 1},
    }
    if excerpt is not None:
        record["excerpt"] = excerpt
        record["excerpt_sha256"] = sha256(excerpt.encode()).hexdigest()
    return record


def case(cid, docs, split="heldout", category="pollination_biology"):
    return {
        "case_id": cid,
        "version": 1,
        "category": category,
        "facet": "POLLINATION",
        "question": f"Which pollinators visit Exemplaria {cid}?",
        "question_origin": {"type": "member_submitted", "model_generated": False, "recorded_at": "2026-10-01"},
        "split": split,
        "source_document_ids": docs,
    }


def review(cid, reviewer, state, supporting=(), contradicting=(), status="expert_reviewed"):
    return {
        "case_id": cid,
        "reviewer_id": reviewer,
        "qualification": "orchid pollination ecologist",
        "reviewed_at": "2026-10-02",
        "independent": True,
        "model_assisted": False,
        "review_status": status,
        "answer_state": state,
        "supporting_document_ids": list(supporting),
        "contradicting_document_ids": list(contradicting),
    }


def suite():
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "label_source": "INDEPENDENT_EXPERT_REVIEW",
        "sources": [source("d1"), source("d2"), source("d3", rights="MODEL_TRANSMISSION_RESTRICTED"), source("d9")],
        "cases": [
            case("agreed", ["d1", "d2"]),
            case("split", ["d1"]),
            case("lonely", ["d1"]),
            case("restricted", ["d3"]),
            case("devcase", ["d9"], split="dev"),
        ],
        "reviews": [
            review("agreed", "r1", "CANDIDATE", ["d1"]),
            review("agreed", "r2", "CANDIDATE", ["d1", "d2"]),
            review("split", "r1", "CANDIDATE", ["d1"]),
            review("split", "r2", "INSUFFICIENT_EVIDENCE"),
            review("lonely", "r1", "CANDIDATE", ["d1"]),
            review("restricted", "r1", "INSUFFICIENT_EVIDENCE"),
            review("restricted", "r2", "INSUFFICIENT_EVIDENCE"),
        ],
    }


def test_committed_suite_is_valid_empty_and_scoring_refuses():
    committed = load_suite()
    report = validate_suite(committed)
    assert report.valid and committed["cases"] == [] and committed["status"] == "AWAITING_CASES"
    result = score_suite(committed, {"x": lambda c: {}})
    assert result["status"] == "REFUSED_NO_SCORABLE_CASES"
    assert "summary" not in result


def test_labels_require_two_independent_expert_reviews_and_keep_disagreement():
    labels = validate_suite(suite()).labels
    assert labels["agreed"].status == SCORABLE and labels["agreed"].expected_state == "CANDIDATE"
    assert labels["agreed"].consensus_documents == ("d1",)
    assert labels["agreed"].acceptable_documents == ("d1", "d2")
    assert labels["split"].status == DISAGREEMENT and labels["split"].expected_state is None
    assert labels["split"].reviewer_states == ("CANDIDATE", "INSUFFICIENT_EVIDENCE")
    assert labels["lonely"].status == INSUFFICIENT_REVIEW


def test_non_expert_or_dependent_reviews_do_not_count():
    data = suite()
    data["reviews"][1]["review_status"] = "human_reviewed"
    assert validate_suite(data).labels["agreed"].status == INSUFFICIENT_REVIEW
    data = suite()
    data["reviews"][1]["independent"] = False
    assert validate_suite(data).labels["agreed"].status == INSUFFICIENT_REVIEW


@pytest.mark.parametrize(
    "mutate,violation",
    [
        (lambda s: s.update(label_source="FIXTURE_CONSTRUCTION"), "FIXTURE_LABELS_NOT_ALLOWED"),
        (lambda s: s["cases"][0]["question_origin"].update(model_generated=True), "CASE_QUESTION_MODEL_GENERATED_OR_UNDECLARED:agreed"),
        (lambda s: s["cases"][0]["question_origin"].pop("model_generated"), "CASE_QUESTION_MODEL_GENERATED_OR_UNDECLARED:agreed"),
        (lambda s: s["cases"][0].update(expected_state="CANDIDATE"), "CASE_CARRIES_ITS_OWN_LABEL:agreed"),
        (lambda s: s["cases"][0].update(category="astrology"), "CASE_CATEGORY_UNKNOWN:agreed"),
        (lambda s: s["cases"][0]["source_document_ids"].append("ghost"), "CASE_SOURCE_NOT_REGISTERED:agreed:ghost"),
        (lambda s: s["reviews"][0].update(model_assisted=True), "REVIEW_MODEL_ASSISTANCE_UNDECLARED_OR_TRUE:agreed:r1"),
        (lambda s: s["reviews"][0].update(supporting_document_ids=["d3"]), "REVIEW_CITES_UNLISTED_SOURCE:agreed:r1:d3"),
        (lambda s: s["reviews"][0].update(supporting_document_ids=[]), "REVIEW_ANSWER_WITHOUT_SUPPORT:agreed:r1"),
        (lambda s: s["reviews"][0].update(answer_state="PROBABLY"), "REVIEW_ANSWER_STATE_INVALID:agreed:r1"),
        (lambda s: s["reviews"].append(review("agreed", "r1", "CANDIDATE", ["d1"])), "REVIEWER_DUPLICATED:agreed"),
        (lambda s: s["reviews"].append(review("nowhere", "r9", "CANDIDATE", ["d1"])), "REVIEW_FOR_UNKNOWN_CASE:nowhere"),
        (lambda s: s["sources"][0].update(rights_state="FREE_PROBABLY"), "SOURCE_RIGHTS_STATE_UNKNOWN:d1"),
        (lambda s: s["sources"][0]["citation"].pop("title"), "SOURCE_CITATION_INCOMPLETE:d1:title"),
        (lambda s: s["sources"].append(source("d5", rights="REUSE_RESTRICTED", excerpt="short")), "SOURCE_EXCERPT_NOT_PERMITTED:d5"),
        (lambda s: s["sources"].append(source("d6", excerpt="x" * 301)), "SOURCE_EXCERPT_TOO_LONG:d6"),
        (lambda s: s["cases"][4].update(source_document_ids=["d1"]), "SPLIT_LEAKAGE_SHARED_SOURCE:d1"),
    ],
)
def test_validator_refuses_manufactured_or_unsafe_ground_truth(mutate, violation):
    data = copy.deepcopy(suite())
    mutate(data)
    report = validate_suite(data)
    assert violation in report.violations


def test_scoring_refuses_an_invalid_suite():
    data = suite()
    data["label_source"] = "FIXTURE_CONSTRUCTION"
    assert score_suite(data, {})["status"] == "REFUSED_INVALID_SUITE"


def answer(state, docs=(), conflicts=(), cost=0.0):
    return {"state": state, "cited_documents": list(docs), "conflict_documents": list(conflicts),
            "latency_ms": 1.0, "provider_calls": 0, "cost_usd": cost}


def test_systems_are_scored_on_the_same_cases_and_disagreement_is_reported_separately():
    systems = {
        "grounded": lambda c: answer("CANDIDATE", ["d1"]) if c["case_id"] == "agreed" else answer("INSUFFICIENT_EVIDENCE"),
        "overconfident": lambda c: answer("CANDIDATE", ["d1", "d9"]),
    }
    result = score_suite(suite(), systems)
    assert result["status"] == "SCORED" and result["scorable_cases"] == 2  # agreed + restricted
    grounded = result["systems"]["grounded"]
    assert grounded["summary"]["state_accuracy"] == 1.0
    assert grounded["summary"]["unsupported_citation_count"] == 0
    loose = result["systems"]["overconfident"]
    assert loose["summary"]["state_accuracy"] == 0.5
    # d9 on "agreed", and d1 + d9 on "restricted" where reviewers cited nothing.
    assert loose["summary"]["unsupported_citation_count"] == 3
    assert grounded["disagreement_cases"][0]["avoided_confident_candidate"] is True
    assert loose["disagreement_cases"][0]["avoided_confident_candidate"] is False
    assert loose["disagreement_cases"][0]["reviewer_states"] == ["CANDIDATE", "INSUFFICIENT_EVIDENCE"]


def test_external_model_systems_never_receive_restricted_sources():
    seen = []

    def model(c):
        seen.append(c["case_id"])
        return answer("INSUFFICIENT_EVIDENCE", cost=0.01)

    result = score_suite(suite(), {"model": model}, external_model_systems=["model"])
    assert "restricted" not in seen
    assert result["systems"]["model"]["skipped_for_rights"] == ["restricted"]
    assert result["systems"]["model"]["summary"]["provider_cost_usd"] == 0.01
    assert model_transmission_permitted(suite(), suite()["cases"][0]) is True


def test_evaluation_case_shape_matches_the_evals_proposal():
    data = suite()
    labels = validate_suite(data).labels
    agreed = to_evaluation_case(data["cases"][0], labels["agreed"])
    assert set(agreed) == {"case_id", "version", "task_class_id", "input_ref", "expected_ref", "provenance"}
    assert agreed["expected_ref"].endswith(":adjudication:agreed")
    assert to_evaluation_case(data["cases"][1], labels["split"])["expected_ref"] is None
