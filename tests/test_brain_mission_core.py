from app.brain_mission.routes import (
    REPOSITORY,
    ExistingBrainMissionAdapter,
    MissionStartIn,
    _retrieve,
    get_mission,
    start_mission,
)
from app.brain_mission.service import BrainMissionService, MissionComponents
from app.evidence_retrieval.engine import RetrievalEngine
from app.semantic_index.memory_repository import MemoryIndexRepository
from app.semantic_index.provider import DeterministicLocalProvider

QUESTION = "Evaluate the accepted taxonomy, geographic distribution, documented pollination biology, conservation concerns, and available mycorrhizal evidence for Laelia anceps."


def _components():
    return MissionComponents(
        retrieve=lambda ctx: {
            "results": [
                {"source_id": str(i), "provenance": {"fixture": True}} for i in range(5)
            ]
        },
        aggregate=lambda ctx: {
            "supporting_evidence": [{"claim": "accepted taxon", "source_id": "0"}],
            "contradicting_evidence": [{"claim": "range disputed", "source_id": "1"}],
        },
        analyze=lambda ctx: {
            "contradicting_evidence": ctx["contradicting_evidence"],
            "missing_evidence": ["species-specific mycorrhizal isolate evidence"],
        },
        interpret=lambda ctx: {
            "confidence": 0.71,
            "conclusions": [
                {
                    "type": "inference",
                    "text": "Evidence is incomplete; expert review is required.",
                }
            ],
        },
        create_ledger=lambda ctx: {"ledger_id": "ledger-fixture", "version": 3},
        validate=lambda ctx: {"valid": True, "blockers": []},
        review_state=lambda ctx: {"status": "HUMAN_REVIEW_REQUIRED"},
        publication_eligibility=lambda ctx: {
            "eligible": False,
            "blockers": ["HUMAN_REVIEW_REQUIRED"],
        },
    )


def test_complete_mission_keeps_review_and_publication_gates():
    result = BrainMissionService(_components()).start(
        question=QUESTION, tenant_id="owner", project_id="project-1", actor="owner"
    )
    assert result["state"] == "AWAITING_HUMAN_REVIEW"
    assert result["reasoning_ledger"] == {"ledger_id": "ledger-fixture", "version": 3}
    assert result["contradicting_evidence"]
    assert result["missing_evidence"]
    assert result["publication_eligibility"] == {
        "eligible": False,
        "automatic_publication": False,
        "blockers": ["HUMAN_REVIEW_REQUIRED"],
    }
    assert result["plan"]["claims_and_inferences_separated"] is True


def test_missing_component_returns_partial_evidence_and_explicit_blocker():
    service = BrainMissionService(
        MissionComponents(retrieve=lambda ctx: {"results": [{"source_id": "fixture"}]})
    )
    result = service.start(
        question=QUESTION, tenant_id="owner", project_id="p", actor="owner"
    )
    assert result["state"] == "BLOCKED"
    assert result["sources"] == [{"source_id": "fixture"}]
    assert result["blockers"][0]["code"] == "AGGREGATE_COMPONENT_UNAVAILABLE"
    assert result["publication_eligibility"]["eligible"] is False


def test_source_and_step_limits_are_enforced():
    result = BrainMissionService(_components()).start(
        question=QUESTION,
        tenant_id="owner",
        project_id="p",
        actor="owner",
        max_sources=2,
        max_steps=3,
    )
    assert len(result["sources"]) == 2
    assert result["steps_executed"] == 3
    assert result["blockers"][0]["code"] == "MAX_EXECUTION_STEPS_REACHED"


def test_route_functions_start_and_retrieve_status(monkeypatch):
    monkeypatch.setattr(
        "app.brain_mission.routes.SERVICE",
        BrainMissionService(_components(), REPOSITORY),
    )
    created = start_mission(
        MissionStartIn(question=QUESTION, project_id="project-1"),
        {"actor": "fixture-owner"},
    )
    fetched = get_mission(created["mission_id"])
    assert fetched["mission_id"] == created["mission_id"]


def _retrieval_engine(facts):
    repository = MemoryIndexRepository()
    provider = DeterministicLocalProvider()
    model_id = repository.ensure_model(provider.metadata)
    for source_id, fact in enumerate(facts, 1):
        text = f"Laelia anceps evidence for {fact['predicate']} {fact['object_value']}."
        repository.documents.append(
            {
                "index_document_id": source_id,
                "source_object_type": "CLAIM",
                "source_object_id": source_id,
                "revision_id": source_id * 10,
                "extraction_run_id": 700 + source_id,
                "parent_type": "CLAIM",
                "parent_id": source_id,
                "anchors": (source_id * 100,),
                "content_hash": f"hash-{source_id}",
                "model_id": model_id,
                "active": True,
                "version": 1,
                "metadata": {
                    "display_policy": "FULL_TEXT_ALLOWED",
                    "document_title": f"Laelia anceps source {source_id}",
                    "locator": {"page": source_id, "span": [0, len(text)]},
                    "candidate_facts": [fact],
                    "taxon": "Laelia anceps",
                    "taxon_identity": {
                        "candidate_taxon_id": 1742,
                        "source_name": "Laelia anceps",
                        "confidence": 1.0,
                    },
                    "claim_role": "CLAIM",
                    "source_class": "PRIMARY",
                    "directness": "DIRECT_OBSERVATION",
                    "provenance": {"fixture_source_id": source_id},
                },
            }
        )
        repository.lexical.append(
            {
                "index_document_id": source_id,
                "normalized_text": text.casefold(),
                "language": "en",
                "title": text,
            }
        )
        repository.vectors.append(
            {
                "index_document_id": source_id,
                "vector": provider.embed_batch([text])[0],
                "active": True,
            }
        )
    return RetrievalEngine(repository, provider)


def test_live_existing_services_advance_to_ledger_without_aggregate_blocker():
    facts = [
        {
            "kind": "TAXON",
            "subject": "Laelia anceps",
            "predicate": "accepted_name",
            "object_value": "Laelia anceps",
            "confidence": 0.82,
        },
        {
            "kind": "GEOGRAPHIC_OCCURRENCE",
            "subject": "Laelia anceps",
            "predicate": "occurs_in",
            "object_value": "Mexico",
            "confidence": 0.82,
        },
        {
            "kind": "ECOLOGICAL_RELATIONSHIP",
            "subject": "Laelia anceps",
            "predicate": "pollinated_by",
            "object_value": "documented bee visitor",
            "confidence": 0.82,
        },
        {
            "kind": "CONSERVATION_ASSERTION",
            "subject": "Laelia anceps",
            "predicate": "conservation_concern",
            "object_value": "habitat loss",
            "confidence": 0.82,
        },
        {
            "kind": "ECOLOGICAL_RELATIONSHIP",
            "subject": "Laelia anceps",
            "predicate": "mycorrhizal_association",
            "object_value": "documented fungal association",
            "confidence": 0.82,
        },
        {
            "kind": "GEOGRAPHIC_OCCURRENCE",
            "subject": "Laelia anceps",
            "predicate": "occurs_in",
            "object_value": "Mexico and Guatemala",
            "confidence": 0.78,
        },
    ]
    adapter = ExistingBrainMissionAdapter()
    retrieval = _retrieval_engine(facts)
    service = BrainMissionService(
        MissionComponents(
            retrieve=lambda ctx: _retrieve(ctx, retrieval),
            aggregate=adapter.aggregate,
            analyze=adapter.analyze,
            interpret=adapter.interpret,
            create_ledger=adapter.create_ledger,
            validate=adapter.validate,
            review_state=adapter.review_state,
            publication_eligibility=adapter.publication_eligibility,
        )
    )
    result = service.start(
        question=QUESTION,
        tenant_id="owner",
        project_id="project-1",
        actor="owner",
        max_sources=6,
    )
    assert result["state"] == "AWAITING_HUMAN_REVIEW"
    assert not any(
        item["code"] == "AGGREGATE_COMPONENT_UNAVAILABLE" for item in result["blockers"]
    )
    assert result["artifacts"]["candidate_status"] == "COMPLETED"
    assert result["artifacts"]["aggregate_status"] == "COMPLETED"
    assert result["artifacts"]["interpretation_id"] > 0
    assert (
        result["reasoning_ledger"]["ledger_id"]
        == "b51e4fd5-4ebf-5a37-9ef3-ea53c11c8b28"
    )
    assert result["reasoning_ledger"]["version"] == 9
    assert result["review_status"] == "HUMAN_REVIEW_REQUIRED"
    assert result["publication_eligibility"]["eligible"] is False
    assert result["publication_eligibility"]["automatic_publication"] is False
