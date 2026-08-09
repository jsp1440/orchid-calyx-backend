from __future__ import annotations

from app.brain.local_observations import (
    LocalObservationRequest,
    handoff_local_observation,
)
from app.brain.plant_diagnostic_context import (
    PlantDiagnosticContextRequest,
    compose_plant_diagnostic_context,
)
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository


def candidate_components():
    repository = MemoryCandidateRepository()
    service = CandidateExtractionService(repository)
    return repository, service


def graph_repository():
    scope = {
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
                payload={"causal_scope": scope},
            ),
            Edge(
                11,
                "promotes",
                2,
                3,
                evidence_class="published_mechanistic_claim",
                confidence_score=0.81,
                payload={"causal_scope": scope},
            ),
        ],
    )


def observation_request():
    return LocalObservationRequest.model_validate(
        {
            "observation_id": "obs-diagnostic-1",
            "plant_record_key": "plant-42",
            "taxon": "Phalaenopsis bellina",
            "observed_at": "2026-08-08T19:00:00-07:00",
            "location_key": "greenhouse-east-bench",
            "response_type": "phenotype",
            "response_label": "New root growth",
            "observation_text": "A new root tip was visible at the evening observation.",
            "environmental_context": {"night_temperature_c": 16},
            "source_object_id": 601,
            "revision_id": 602,
            "extraction_run_id": 603,
            "source_anchors": [{"anchor_id": 604}],
        }
    )


def diagnostic_request():
    return PlantDiagnosticContextRequest.model_validate(
        {
            "plant_record_key": "plant-42",
            "reasoning": {
                "subject_node_id": 1,
                "applicability_scope": {
                    "scope_class": "bounded",
                    "taxa": ["Phalaenopsis bellina"],
                    "tissues": ["root"],
                },
                "causal_only": True,
            },
        }
    )


def test_composer_keeps_canonical_and_local_evidence_separate():
    components = candidate_components()
    handoff_local_observation(observation_request(), components)

    result = compose_plant_diagnostic_context(
        graph_repository(),
        diagnostic_request(),
        components,
    )

    assert result["summary"]["applicable_canonical_path_count"] > 0
    assert result["summary"]["local_observation_count"] == 1
    assert result["summary"]["has_applicable_canonical_context"] is True
    assert result["summary"]["has_local_context"] is True
    assert result["canonical_reasoning"]["scope_summary"]["safe_to_generalize"] is True
    assert result["local_observation_context"]["species_level_generalization"] is False
    assert (
        result["interpretation_policy"][
            "canonical_mechanisms_and_local_observations_are_separate_channels"
        ]
        is True
    )
    assert (
        result["interpretation_policy"]["local_observation_implies_canonical_mechanism"]
        is False
    )


def test_composer_does_not_invent_local_context_when_none_exists():
    components = candidate_components()

    result = compose_plant_diagnostic_context(
        graph_repository(),
        diagnostic_request(),
        components,
    )

    assert result["summary"]["local_observation_count"] == 0
    assert result["summary"]["has_local_context"] is False
    assert result["local_observation_context"]["observations"] == []


def test_out_of_scope_canonical_path_remains_visible_but_not_applicable():
    components = candidate_components()
    request = diagnostic_request().model_copy(
        update={
            "reasoning": diagnostic_request().reasoning.model_copy(
                update={
                    "applicability_scope": {
                        "scope_class": "bounded",
                        "taxa": ["Phalaenopsis bellina"],
                        "tissues": ["leaf"],
                    }
                }
            )
        }
    )

    request = PlantDiagnosticContextRequest.model_validate(request.model_dump())
    result = compose_plant_diagnostic_context(graph_repository(), request, components)

    assert result["summary"]["out_of_scope_canonical_path_count"] > 0
    assert result["summary"]["has_applicable_canonical_context"] is False
    assert any(
        path["applicability"]["status"] == "out_of_scope"
        for path in result["canonical_reasoning"]["paths"]
    )


def test_composer_is_read_only_and_has_no_publication_authority():
    components = candidate_components()
    result = compose_plant_diagnostic_context(
        graph_repository(),
        diagnostic_request(),
        components,
    )

    assert result["governance"]["read_only"] is True
    assert result["governance"]["canonical_graph_mutated"] is False
    assert result["governance"]["candidate_knowledge_mutated"] is False
    assert result["governance"]["scientific_publication_authority"] is False
    assert (
        result["interpretation_policy"]["automatic_scientific_claim_generation"]
        is False
    )
    assert result["interpretation_policy"]["automatic_publication"] is False
