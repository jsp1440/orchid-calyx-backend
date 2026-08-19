from __future__ import annotations

from app.calyx_conversation.evidence_synthesis import (
    SYNTHESIS_CONTRACT_VERSION,
    build_synthesis_packet,
)
from app.calyx_conversation.provider_runtime import compact_governed_context


def _context():
    return {
        "casual": False,
        "interaction_context": {"surface": "illustrated-orchid-lexicon"},
        "retrieval": {
            "results": [
                {
                    "result_id": "local-1",
                    "object_type": "LITERATURE",
                    "title": "Canonical orchid physiology record",
                    "authorized_excerpt": "CAM physiology is associated with nocturnal carbon uptake in the supplied orchid record.",
                    "revision_id": 4,
                }
            ],
            "external_literature": {
                "results": [
                    {
                        "title": "External orchid CAM paper",
                        "abstract": "The paper reports nocturnal gas exchange in an orchid sample.",
                        "doi": "10.1000/example",
                        "source": "Europe PMC",
                        "review_state": "REVIEW_REQUIRED",
                    }
                ]
            },
        },
        "continuum": {
            "taxa": [
                {
                    "genus": "Phalaenopsis",
                    "environmental_facts": [
                        {"statement": "The supplied graph record associates the taxon with humid forest habitat."}
                    ],
                }
            ]
        },
        "climate": {"products": []},
        "mission": {
            "mission_id": "mission-1",
            "question": "How does orchid physiology connect to habitat?",
            "supporting_evidence": [
                {
                    "candidate_id": "support-1",
                    "subject": "orchid CAM physiology",
                    "predicate": "is associated with",
                    "value": "nocturnal carbon uptake",
                }
            ],
            "contradicting_evidence": [
                {
                    "candidate_id": "conflict-1",
                    "subject": "strength of habitat generalization",
                    "predicate": "is limited by",
                    "value": "taxon-specific variation",
                }
            ],
            "conclusions": [
                {
                    "type": "inference",
                    "text": "The governed evidence supports a physiology-habitat connection, but not a genus-wide causal generalization.",
                }
            ],
            "missing_evidence": ["species-level comparative measurements"],
            "confidence": 0.72,
            "review_status": "HUMAN_REVIEW_REQUIRED",
        },
        "mission_error": None,
        "epistemic_policy": {"continuum_first": True},
        "deliverable_capabilities": {"structured_citations": True},
        "provider_configuration": {"selected": "openai-runtime-autodetect"},
    }


def test_build_synthesis_packet_normalizes_source_families_and_conflicts():
    context = _context()
    packet = build_synthesis_packet(
        question=context["mission"]["question"],
        retrieval=context["retrieval"],
        continuum=context["continuum"],
        climate=context["climate"],
        mission=context["mission"],
        mission_error=None,
        interaction_context=context["interaction_context"],
    )

    assert packet["contract_version"] == SYNTHESIS_CONTRACT_VERSION
    assert packet["fingerprint"]
    families = {item["source_family"] for item in packet["evidence_items"]}
    assert {"continuum_retrieval", "external_literature", "knowledge_graph", "brain_mission"}.issubset(families)
    assert packet["reconciliation"]["unresolved_conflict"] is True
    assert "species-level comparative measurements" in packet["reconciliation"]["missing_evidence"]
    assert packet["candidate_conclusions"][0]["text"].startswith("The governed evidence supports")
    assert packet["synthesis_plan"]["do_not_narrate_sources_sequentially"] is True


def test_model_facing_context_uses_semantic_packet_not_raw_subsystem_payloads():
    compact = compact_governed_context(_context())

    assert "synthesis_packet" in compact
    assert compact["synthesis_packet"]["contract_version"] == SYNTHESIS_CONTRACT_VERSION
    assert "retrieval" not in compact
    assert "continuum" not in compact
    assert "climate" not in compact
    assert "mission" not in compact
    assert compact["synthesis_packet"]["synthesis_plan"]["integrate_across_sources"] is True


def test_external_literature_remains_review_required_after_normalization():
    packet = build_synthesis_packet(
        question="What does the literature say?",
        retrieval=_context()["retrieval"],
        continuum={},
        climate={},
        mission=None,
        mission_error=None,
    )
    external = [item for item in packet["evidence_items"] if item["source_family"] == "external_literature"]
    assert external
    assert all(item["status"] == "review_required" for item in external)
    assert all(item["review_state"] == "REVIEW_REQUIRED" for item in external)
    assert packet["reconciliation"]["external_literature_review_required"] is True
