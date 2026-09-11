"""PHALAENOPSIS THERMAL-TRAIT REASONING BENCHMARK.

This is a scientific-synthesis acceptance test for Calyx, not a lookup test.

The question deliberately requires Calyx to combine trait, ecology, occurrence,
climate-proxy, literature, and phylogenetic-confounding evidence while keeping
three epistemic categories separate:

1. directly supported pattern;
2. plausible but not-yet-tested candidate traits;
3. analyses still required before claiming independent prediction.

The fixture statements are test evidence only. They are not publication into the
Orchid Continuum Knowledge Graph and must never be treated as canonical truth.
"""

from __future__ import annotations

from app.calyx_conversation.evidence_synthesis import build_synthesis_packet
from app.calyx_conversation.provider import DeterministicGovernedReplyProvider

QUESTION = (
    "Which morphological, anatomical, physiological and life-history traits distinguish "
    "cool-growing Phalaenopsis species from warm-growing ones, and which of those traits "
    "remain predictive after accounting for elevation, precipitation, geography and "
    "phylogenetic relatedness?"
)

RETRIEVAL = {
    "results": [
        {
            "result_id": "trait-leaf-persistence",
            "object_type": "trait_record",
            "title": "Phalaenopsis leaf persistence and dormancy",
            "authorized_excerpt": (
                "Cool-growing Phalaenopsis in the seasonal montane group include deciduous "
                "or semi-deciduous species with seasonal dormancy, while many warm-growing "
                "lowland Phalaenopsis retain evergreen leaves."
            ),
            "review_state": "CANONICAL_OR_GOVERNED",
            "citation": {"source": "fixture-trait"},
            "revision_id": "fixture-trait-r1",
        },
        {
            "result_id": "occurrence-elevation",
            "object_type": "occurrence_summary",
            "title": "Phalaenopsis thermal niche and elevation",
            "authorized_excerpt": (
                "Cool-growing Phalaenopsis records in this comparison are associated with "
                "montane elevations and more seasonal environments, whereas warm-growing "
                "comparison species include lowland wet-tropical records."
            ),
            "review_state": "CANONICAL_OR_GOVERNED",
            "citation": {"source": "fixture-occurrence"},
            "revision_id": "fixture-occurrence-r1",
        },
    ],
    "total_eligible_results": 2,
    "external_literature": {
        "status": "available",
        "result_count": 1,
        "results": [
            {
                "title": "Comparative leaf anatomy in Phalaenopsis",
                "abstract": (
                    "Phalaenopsis species differ in stomatal density, epidermal traits and "
                    "leaf thickness, but the study did not test whether those anatomical "
                    "traits independently predict cool-growing versus warm-growing thermal niches."
                ),
                "doi": "10.0000/phalaenopsis.fixture",
                "source": "Europe PMC",
                "review_state": "REVIEW_REQUIRED",
            }
        ],
    },
}

CONTINUUM = {
    "candidate_genera": ["Phalaenopsis"],
    "resolved_genera": ["Phalaenopsis"],
    "taxa": [
        {
            "genus": "Phalaenopsis",
            "environmental_facts": [
                {
                    "statement": (
                        "Phalaenopsis thermal niche comparisons must separate elevation and "
                        "precipitation effects from organismal trait effects."
                    ),
                    "source": "fixture-environment",
                }
            ],
        }
    ],
    "semantic_links": [],
    "diagnostics": [],
}

CLIMATE = {"requested": False, "status": "not_relevant", "products": []}

MISSION = {
    "mission_id": "mission-phalaenopsis-thermal-traits",
    "state": "COMPLETED",
    "confidence": 0.72,
    "review_status": "UNREVIEWED_FIXTURE",
    "supporting_evidence": [
        {
            "subject": "seasonal leaf persistence and dormancy",
            "predicate": "distinguish",
            "value": "the current cool-growing and warm-growing Phalaenopsis comparison",
            "candidate_id": "candidate-life-history",
            "source_revision_id": "fixture-trait-r1",
            "source_anchor_ids": ["trait-leaf-persistence"],
        },
        {
            "subject": "thermal niche",
            "predicate": "covaries with",
            "value": "elevation and environmental seasonality in the current Phalaenopsis comparison",
            "candidate_id": "candidate-environment",
            "source_revision_id": "fixture-occurrence-r1",
            "source_anchor_ids": ["occurrence-elevation"],
        },
    ],
    "contradicting_evidence": [
        {
            "subject": "leaf thickness alone",
            "predicate": "is not uniquely diagnostic of",
            "value": "cool-growing Phalaenopsis because thick or succulent leaves can also occur under warm drought or exposed-canopy conditions",
            "candidate_id": "counter-leaf-thickness",
            "source_revision_id": "fixture-counter-r1",
            "source_anchor_ids": ["trait-leaf-persistence"],
        },
        {
            "subject": "phylogenetic relatedness",
            "predicate": "confounds",
            "value": "an uncorrected association between seasonal dormancy and cool-growing Phalaenopsis when cool-adapted taxa cluster in one lineage",
            "candidate_id": "counter-phylogeny",
            "source_revision_id": "fixture-counter-r2",
            "source_anchor_ids": ["trait-leaf-persistence"],
        },
    ],
    "missing_evidence": [
        "species-level thermal-niche estimates derived from georeferenced wild occurrences",
        "a standardized Phalaenopsis trait matrix including leaf persistence, dormancy and anatomy",
        "a phylogenetically controlled comparative model that includes elevation, precipitation and geography",
    ],
    "conclusions": [
        {
            "type": "provisional_synthesis",
            "text": (
                "The strongest currently supported discriminator is seasonal leaf persistence "
                "and dormancy, not leaf thickness alone. The available evidence does not yet "
                "establish which traits independently predict Phalaenopsis thermal niche after "
                "controlling for elevation, precipitation, geography and phylogenetic relatedness."
            ),
            "claim_ids": ["question:0", "question:1"],
        }
    ],
    "sources": [
        {
            "title": "Phalaenopsis thermal-trait fixture",
            "citation": {
                "document_title": "Phalaenopsis thermal-trait fixture",
                "locator": "benchmark fixture",
                "revision_id": "fixture-r1",
            },
        }
    ],
    "artifacts": {"evidence_packet_id": "ep-phalaenopsis-thermal-traits"},
}


def packet():
    return build_synthesis_packet(
        question=QUESTION,
        retrieval=RETRIEVAL,
        continuum=CONTINUUM,
        climate=CLIMATE,
        mission=MISSION,
        mission_error=None,
    )


def reply():
    return DeterministicGovernedReplyProvider().generate(
        messages=[{"role": "user", "content": QUESTION}],
        governed_context={
            "casual": False,
            "retrieval": RETRIEVAL,
            "continuum": CONTINUUM,
            "climate": CLIMATE,
            "mission": MISSION,
        },
    )


def test_phalaenopsis_question_produces_an_answer_first_integrated_synthesis():
    result = reply()
    text = result.text.lower()

    assert "seasonal leaf persistence" in text
    assert "dormancy" in text
    assert "leaf thickness alone" in text
    assert "phylogenetic relatedness" in text
    assert result.synthesis_structure is not None
    assert result.synthesis_structure["integrated_across_source_families"] is True
    assert any(
        len(item["source_families"]) > 1
        for item in result.synthesis_structure["claim_coverage"]
    )


def test_phalaenopsis_benchmark_does_not_promote_candidate_anatomical_traits_to_predictors():
    result = reply()
    text = result.text.lower()

    assert "does not yet establish" in text
    assert "stomatal density" in text or result.synthesis_structure["external_literature_review_required"] is True
    assert "leaf thickness alone" in text
    assert "isn't all pointing one way" in text or "hold the conclusion loosely" in text
    assert result.synthesis_structure["unresolved_conflict"] is True


def test_phalaenopsis_benchmark_requires_phylogenetically_controlled_analysis_before_independent_prediction():
    result = reply()
    structure = result.synthesis_structure
    assert structure is not None

    missing = " ".join(structure["missing_evidence"]).lower()
    assert "species-level thermal-niche estimates" in missing
    assert "standardized phalaenopsis trait matrix" in missing
    assert "phylogenetically controlled comparative model" in missing
    assert "elevation" in missing
    assert "precipitation" in missing
    assert "geography" in missing


def test_phalaenopsis_benchmark_preserves_provenance_review_state_and_read_only_boundary():
    synthesis = packet()
    result = reply()
    structure = result.synthesis_structure
    assert structure is not None

    families = set(synthesis["reconciliation"]["source_families"])
    assert {"brain_mission", "continuum_retrieval", "external_literature", "knowledge_graph"} <= families
    assert synthesis["reconciliation"]["external_literature_review_required"] is True
    assert synthesis["publication_boundary"] == {
        "read_only": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }
    assert structure["governed_provenance"]["evidence_packet_id"] == "ep-phalaenopsis-thermal-traits"
    assert any("Phalaenopsis thermal-trait fixture" in item for item in structure["citations"])
