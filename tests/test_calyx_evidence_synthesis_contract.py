from __future__ import annotations

from types import SimpleNamespace

from app.calyx_conversation import speak_routes
from app.calyx_conversation.evidence_synthesis import (
    SYNTHESIS_CONTRACT_VERSION,
    build_synthesis_packet,
)
from app.calyx_conversation.provider import GeneratedReply
from app.calyx_conversation.provider_runtime import compact_governed_context
from app.calyx_conversation.store import ConversationStore


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


def test_realistic_question_traces_through_full_calyx_turn(monkeypatch, capsys):
    """Trace one realistic question through retrieval -> mission -> semantic handoff -> answer.

    The provider is deterministic and test-local so CI never spends model tokens, but it
    consumes exactly the compact semantic context supplied to the production OpenAI
    runtime. This makes the handoff observable end-to-end without faking the retrieval
    or reconciliation stages after they have run.
    """

    question = (
        "Phalaenopsis are often described as CAM orchids from humid forests. "
        "How can CAM physiology make biological sense in a humid habitat, and how strongly can we generalize that across the genus?"
    )
    trace: dict[str, object] = {}
    store = ConversationStore(dsn="")
    monkeypatch.setattr(speak_routes, "STORE", store)

    def retrieval(message, mode, limit, internal_access):
        trace["retrieval_question"] = message
        return {
            "results": [
                {
                    "result_id": "cam-local-1",
                    "object_type": "LITERATURE",
                    "title": "Canonical CAM physiology record",
                    "authorized_excerpt": (
                        "The governed record links CAM physiology with nocturnal CO2 uptake and daytime stomatal closure, "
                        "a water-conserving gas-exchange strategy."
                    ),
                    "revision_id": 9,
                }
            ],
            "total_eligible_results": 1,
            "retrieval_mode": mode,
        }

    monkeypatch.setattr(speak_routes, "_retrieval", retrieval)
    monkeypatch.setattr(
        speak_routes,
        "augment_retrieval_with_external_literature",
        lambda result, message, limit: {
            **result,
            "external_literature": {
                "status": "available",
                "results": [
                    {
                        "title": "CAM gas exchange in epiphytic orchids",
                        "abstract": (
                            "Review-required external literature reports nocturnal gas exchange in epiphytic orchids and notes that "
                            "humid forest conditions do not eliminate episodic water limitation in canopy microhabitats."
                        ),
                        "doi": "10.1000/cam-orchid",
                        "source": "Europe PMC",
                        "review_state": "REVIEW_REQUIRED",
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(
        speak_routes,
        "build_continuum_context",
        lambda message: {
            "candidate_genera": ["Phalaenopsis"],
            "resolved_genera": ["Phalaenopsis"],
            "taxa": [
                {
                    "genus": "Phalaenopsis",
                    "environmental_facts": [
                        {
                            "statement": (
                                "Canonical graph context associates sampled Phalaenopsis taxa with humid forest and epiphytic habitats."
                            )
                        }
                    ],
                }
            ],
            "read_only": True,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
            "diagnostics": [],
        },
    )
    monkeypatch.setattr(
        speak_routes,
        "build_seasonal_climate_context",
        lambda message: {"requested": False, "status": "not_relevant", "products": []},
    )

    def mission_start(**kwargs):
        trace["mission_question"] = kwargs["question"]
        return {
            "mission_id": "mission-cam-e2e",
            "question": kwargs["question"],
            "state": "AWAITING_HUMAN_REVIEW",
            "sources": [],
            "supporting_evidence": [
                {
                    "candidate_id": "support-cam",
                    "subject": "CAM physiology",
                    "predicate": "can conserve water through",
                    "value": "nighttime CO2 uptake with reduced daytime stomatal opening",
                },
                {
                    "candidate_id": "support-habitat",
                    "subject": "epiphytic humid-forest orchids",
                    "predicate": "can still experience",
                    "value": "intermittent substrate and canopy water limitation",
                },
            ],
            "contradicting_evidence": [
                {
                    "candidate_id": "limit-genus",
                    "subject": "genus-wide CAM generalization",
                    "predicate": "is limited by",
                    "value": "species-level physiological variation and incomplete comparative measurements",
                }
            ],
            "conclusions": [
                {
                    "type": "inference",
                    "text": (
                        "CAM can be biologically advantageous in humid epiphytic habitats because atmospheric humidity does not guarantee a continuous root-zone water supply; "
                        "however, the supplied evidence does not justify treating every Phalaenopsis species as physiologically identical."
                    ),
                }
            ],
            "missing_evidence": ["genus-wide species-level comparative gas-exchange measurements"],
            "confidence": 0.78,
            "review_status": "HUMAN_REVIEW_REQUIRED",
            "publication_eligibility": {"eligible": False, "automatic_publication": False, "blockers": ["HUMAN_REVIEW_REQUIRED"]},
        }

    monkeypatch.setattr(speak_routes, "BRAIN_MISSION_SERVICE", SimpleNamespace(start=mission_start))

    class TraceSemanticProvider:
        provider_name = "trace-semantic-provider"
        model_name = "semantic-contract-test"

        def generate(self, *, messages, governed_context):
            compact = compact_governed_context(governed_context)
            trace["model_context"] = compact
            packet = compact["synthesis_packet"]
            conclusion = packet["candidate_conclusions"][0]["text"]
            missing = packet["reconciliation"]["missing_evidence"]
            conflicts = packet["reconciliation"]["unresolved_conflict"]
            answer = (
                conclusion
                + " In other words, a humid atmosphere and a continuously wet root environment are not the same ecological condition, "
                + "so CAM can still make functional sense for an epiphyte whose water supply is episodic."
                + (" The genus-wide claim should remain qualified because conflicting/limiting evidence is present." if conflicts else "")
                + (f" The main remaining gap is {missing[0]}." if missing else "")
            )
            trace["final_answer"] = answer
            return GeneratedReply(
                text=answer,
                provider=self.provider_name,
                model=self.model_name,
                request_hash="trace-e2e-request",
            )

    monkeypatch.setattr(speak_routes, "configured_reply_provider", lambda: TraceSemanticProvider())

    created = speak_routes.create_conversation(
        speak_routes.ConversationCreateRequest(title="CAM trace", project_id="calyx-e2e"),
        {"subject": "trace-owner"},
    )
    result = speak_routes.append_turn(
        created["conversation_id"],
        speak_routes.ConversationTurnRequest(message=question, research_mode="always", retrieval_limit=12),
        {"subject": "trace-owner"},
    )

    compact = trace["model_context"]
    packet = compact["synthesis_packet"]
    families = set(packet["reconciliation"]["source_families"])

    assert trace["retrieval_question"] == question
    assert question in trace["mission_question"]
    assert packet["question"]
    assert {"continuum_retrieval", "external_literature", "knowledge_graph", "brain_mission"}.issubset(families)
    assert packet["reconciliation"]["unresolved_conflict"] is True
    assert packet["synthesis_plan"]["do_not_narrate_sources_sequentially"] is True
    assert "retrieval" not in compact and "continuum" not in compact and "mission" not in compact
    assert "humid atmosphere and a continuously wet root environment are not the same" in result["answer"]
    assert "genus-wide claim should remain qualified" in result["answer"]
    assert "Europe PMC returned" not in result["answer"]
    assert "Knowledge Graph nodes=" not in result["answer"]

    print("CALYX_E2E_TRACE question:", question)
    print("CALYX_E2E_TRACE source_families:", sorted(families))
    print("CALYX_E2E_TRACE conflict:", packet["reconciliation"]["unresolved_conflict"])
    print("CALYX_E2E_TRACE missing_evidence:", packet["reconciliation"]["missing_evidence"])
    print("CALYX_E2E_TRACE candidate_conclusion:", packet["candidate_conclusions"][0]["text"])
    print("CALYX_E2E_TRACE final_answer:", result["answer"])
    captured = capsys.readouterr().out
    assert "CALYX_E2E_TRACE final_answer:" in captured
