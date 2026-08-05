from app.brain_mission.routes import MissionStartIn, REPOSITORY, get_mission, start_mission
from app.brain_mission.service import BrainMissionService, MissionComponents


QUESTION = "Evaluate the accepted taxonomy, geographic distribution, documented pollination biology, conservation concerns, and available mycorrhizal evidence for Laelia anceps."


def _components():
    return MissionComponents(
        retrieve=lambda ctx: {"results": [{"source_id": str(i), "provenance": {"fixture": True}} for i in range(5)]},
        aggregate=lambda ctx: {"supporting_evidence": [{"claim": "accepted taxon", "source_id": "0"}], "contradicting_evidence": [{"claim": "range disputed", "source_id": "1"}]},
        analyze=lambda ctx: {"contradicting_evidence": ctx["contradicting_evidence"], "missing_evidence": ["species-specific mycorrhizal isolate evidence"]},
        interpret=lambda ctx: {"confidence": 0.71, "conclusions": [{"type": "inference", "text": "Evidence is incomplete; expert review is required."}]},
        create_ledger=lambda ctx: {"ledger_id": "ledger-fixture", "version": 3},
        validate=lambda ctx: {"valid": True, "blockers": []},
        review_state=lambda ctx: {"status": "HUMAN_REVIEW_REQUIRED"},
        publication_eligibility=lambda ctx: {"eligible": False, "blockers": ["HUMAN_REVIEW_REQUIRED"]},
    )


def test_complete_mission_keeps_review_and_publication_gates():
    result = BrainMissionService(_components()).start(
        question=QUESTION, tenant_id="owner", project_id="project-1", actor="owner"
    )
    assert result["state"] == "AWAITING_HUMAN_REVIEW"
    assert result["reasoning_ledger"] == {"ledger_id": "ledger-fixture", "version": 3}
    assert result["contradicting_evidence"]
    assert result["missing_evidence"]
    assert result["publication_eligibility"] == {"eligible": False, "automatic_publication": False, "blockers": ["HUMAN_REVIEW_REQUIRED"]}
    assert result["plan"]["claims_and_inferences_separated"] is True


def test_missing_component_returns_partial_evidence_and_explicit_blocker():
    service = BrainMissionService(MissionComponents(retrieve=lambda ctx: {"results": [{"source_id": "fixture"}]}))
    result = service.start(question=QUESTION, tenant_id="owner", project_id="p", actor="owner")
    assert result["state"] == "BLOCKED"
    assert result["sources"] == [{"source_id": "fixture"}]
    assert result["blockers"][0]["code"] == "AGGREGATE_COMPONENT_UNAVAILABLE"
    assert result["publication_eligibility"]["eligible"] is False


def test_source_and_step_limits_are_enforced():
    result = BrainMissionService(_components()).start(
        question=QUESTION, tenant_id="owner", project_id="p", actor="owner", max_sources=2, max_steps=3
    )
    assert len(result["sources"]) == 2
    assert result["steps_executed"] == 3
    assert result["blockers"][0]["code"] == "MAX_EXECUTION_STEPS_REACHED"


def test_route_functions_start_and_retrieve_status(monkeypatch):
    monkeypatch.setattr("app.brain_mission.routes.SERVICE", BrainMissionService(_components(), REPOSITORY))
    created = start_mission(MissionStartIn(question=QUESTION, project_id="project-1"), {"actor": "fixture-owner"})
    fetched = get_mission(created["mission_id"])
    assert fetched["mission_id"] == created["mission_id"]
