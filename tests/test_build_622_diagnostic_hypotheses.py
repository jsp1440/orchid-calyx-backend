from __future__ import annotations

from app.brain.diagnostic_hypotheses import (
    DiagnosticHypothesisRequest,
    rank_diagnostic_hypotheses,
)
from app.brain.local_observations import LocalObservationRequest, handoff_local_observation
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository


def candidate_components():
    repository = MemoryCandidateRepository()
    return repository, CandidateExtractionService(repository)


def graph_repository(scope=None):
    bounded = scope or {
        "scope_class": "bounded",
        "taxa": ["phalaenopsis bellina"],
        "tissues": ["root"],
    }
    return InMemoryGraphRepository(
        [
            Node(1, "environment", "environment:cool-nights", "Cool nights"),
            Node(2, "physiology", "physiology:respiration", "Respiration"),
            Node(3, "phenotype", "phenotype:root-growth", "Root growth"),
        ],
        [
            Edge(
                10,
                "inhibits",
                1,
                2,
                evidence_class="published_mechanistic_claim",
                confidence_score=0.88,
                payload={"causal_scope": bounded},
            ),
            Edge(
                11,
                "promotes",
                2,
                3,
                evidence_class="published_mechanistic_claim",
                confidence_score=0.81,
                payload={"causal_scope": bounded},
            ),
        ],
    )


def request(tissue="root", include_indeterminate=True):
    return DiagnosticHypothesisRequest.model_validate(
        {
            "context": {
                "plant_record_key": "plant-42",
                "reasoning": {
                    "subject_node_id": 1,
                    "applicability_scope": {
                        "scope_class": "bounded",
                        "taxa": ["Phalaenopsis bellina"],
                        "tissues": [tissue],
                    },
                    "causal_only": True,
                },
            },
            "include_indeterminate": include_indeterminate,
        }
    )


def add_local_observation(components):
    handoff_local_observation(
        LocalObservationRequest.model_validate(
            {
                "observation_id": "obs-hypothesis-1",
                "plant_record_key": "plant-42",
                "taxon": "Phalaenopsis bellina",
                "observed_at": "2026-08-08T20:00:00-07:00",
                "location_key": "greenhouse-east-bench",
                "response_type": "phenotype",
                "response_label": "New root growth",
                "observation_text": "A new root tip was visible.",
                "source_object_id": 701,
                "revision_id": 702,
                "extraction_run_id": 703,
                "source_anchors": [{"anchor_id": 704}],
            }
        ),
        components,
    )


def test_applicable_paths_become_ranked_hypotheses():
    components = candidate_components()
    result = rank_diagnostic_hypotheses(graph_repository(), request(), components)

    assert result["hypothesis_count"] > 0
    assert all(item["applicability_status"] == "applicable" for item in result["hypotheses"])
    scores = [item["rank_score"] for item in result["hypotheses"]]
    assert scores == sorted(scores, reverse=True)
    assert result["governance"]["hypotheses_are_not_scientific_claims"] is True


def test_local_observation_does_not_raise_rank_or_causal_confidence():
    without_local = candidate_components()
    baseline = rank_diagnostic_hypotheses(graph_repository(), request(), without_local)

    with_local = candidate_components()
    add_local_observation(with_local)
    enriched = rank_diagnostic_hypotheses(graph_repository(), request(), with_local)

    assert [item["rank_score"] for item in baseline["hypotheses"]] == [
        item["rank_score"] for item in enriched["hypotheses"]
    ]
    assert enriched["local_observation_count"] == 1
    assert all(
        item["local_context"]["rank_score_contribution"] == 0.0
        for item in enriched["hypotheses"]
    )
    assert all(
        item["local_context"]["causal_confirmation"] is False
        for item in enriched["hypotheses"]
    )


def test_out_of_scope_paths_are_excluded_not_ranked():
    components = candidate_components()
    result = rank_diagnostic_hypotheses(
        graph_repository(),
        request(tissue="leaf"),
        components,
    )

    assert result["hypothesis_count"] == 0
    assert result["excluded_out_of_scope"]
    assert result["ranking_policy"]["out_of_scope_paths_ranked"] is False


def test_indeterminate_scope_is_penalized_and_remains_unresolved():
    components = candidate_components()
    repo = graph_repository({"scope_class": "unknown"})
    result = rank_diagnostic_hypotheses(repo, request(), components)

    assert result["hypothesis_count"] > 0
    assert all(item["applicability_status"] == "indeterminate" for item in result["hypotheses"])
    assert all(item["scoring_basis"] == "scope_indeterminate_penalty" for item in result["hypotheses"])
    assert all(
        item["rank_score"] <= float(item["canonical_path_confidence"]) * 0.5 + 1e-9
        for item in result["hypotheses"]
    )


def test_indeterminate_paths_can_be_excluded_by_request():
    components = candidate_components()
    repo = graph_repository({"scope_class": "unknown"})
    result = rank_diagnostic_hypotheses(
        repo,
        request(include_indeterminate=False),
        components,
    )

    assert result["hypothesis_count"] == 0


def test_ranker_has_no_candidate_or_publication_authority():
    components = candidate_components()
    result = rank_diagnostic_hypotheses(graph_repository(), request(), components)

    assert result["governance"]["read_only"] is True
    assert result["governance"]["automatic_candidate_creation"] is False
    assert result["governance"]["automatic_publication"] is False
    assert result["governance"]["canonical_graph_mutated"] is False
    assert result["governance"]["candidate_knowledge_mutated"] is False
