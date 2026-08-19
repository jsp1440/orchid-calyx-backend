from __future__ import annotations

from app.calyx_conversation import external_literature, speak_routes


def test_wet_winter_query_plan_prioritizes_waterlogging_and_rot():
    question = (
        "How should Cymbidium, Laelia, Masdevallia and Lycaste be managed "
        "through a very wet El Niño winter with prolonged rain and saturated pots?"
    )
    plan = external_literature._query_plan(question)
    joined = " ".join(plan).casefold()
    assert "waterlogging" in joined or "root rot" in joined
    assert "phytophthora" in joined or "pythium" in joined


def test_wet_winter_relevance_demotes_flowering_only_distractor():
    question = "What are the risks of prolonged winter rain and waterlogging for orchids?"
    wet_record = {
        "title": "Waterlogging and root hypoxia in orchid roots",
        "abstract": "Root rot, hypoxia and prolonged moisture were evaluated in orchids.",
    }
    flower_record = {
        "title": "Hormonal regulation of orchid flowering",
        "abstract": "This study examines flower bud differentiation and reflowering.",
    }
    assert external_literature._relevance_score(
        wet_record, question
    ) > external_literature._relevance_score(flower_record, question)


def test_mission_question_preserves_subject_and_tail_for_long_turn():
    message = "SUBJECT-WET-WINTER " + ("orchid physiology " * 100) + " FINAL-CONSTRAINT"
    result = speak_routes._mission_question("old history", message)
    assert "SUBJECT-WET-WINTER" in result
    assert "FINAL-CONSTRAINT" in result
    assert len(result) <= 1000


def _stub_non_retrieval_context(monkeypatch):
    monkeypatch.setattr(
        speak_routes,
        "_safe_continuum_context",
        lambda message: {"resolved_genera": [], "taxa": []},
    )
    monkeypatch.setattr(
        speak_routes,
        "_safe_climate_context",
        lambda message: {"status": "not_relevant", "products": []},
    )


def test_auto_mode_defers_canonical_mission_when_only_external_evidence(monkeypatch):
    monkeypatch.setattr(
        speak_routes,
        "_safe_retrieval",
        lambda message, retrieval_limit: {
            "results": [],
            "total_eligible_results": 0,
            "status": "local_empty_external_literature_available",
            "external_literature": {
                "results": [{"title": "Relevant orchid paper"}],
                "result_count": 1,
                "status": "available",
            },
            "research_index_ingest": {
                "status": "indexed_for_research",
                "evidence_set_id": "abc123",
                "review_required": True,
            },
        },
    )
    _stub_non_retrieval_context(monkeypatch)

    def mission_must_not_run(**kwargs):
        raise AssertionError("canonical mission should be deferred for external-only auto turn")

    monkeypatch.setattr(speak_routes.BRAIN_MISSION_SERVICE, "start", mission_must_not_run)

    retrieval, _continuum, _climate, mission, mission_error, casual = (
        speak_routes._run_governed_turn(
            owner="owner",
            conversation_id="conversation",
            project_id="project",
            message="Please synthesize the wet-winter orchid evidence for me.",
            research_mode="auto",
            retrieval_limit=8,
        )
    )

    assert casual is False
    assert mission is None
    assert mission_error is None
    assert retrieval["conversation_synthesis_mode"] == "external_review_literature"
    assert retrieval["canonical_mission_deferred"] is True


def test_auto_mode_defers_doomed_mission_when_all_retrieval_is_empty(monkeypatch):
    monkeypatch.setattr(
        speak_routes,
        "_safe_retrieval",
        lambda message, retrieval_limit: {
            "results": [],
            "total_eligible_results": 0,
            "status": "unavailable",
            "error": "SEMANTIC_INDEX_DATABASE_UNAVAILABLE",
            "external_literature": {
                "results": [],
                "result_count": 0,
                "status": "empty",
            },
        },
    )
    _stub_non_retrieval_context(monkeypatch)

    def mission_must_not_run(**kwargs):
        raise AssertionError("zero-source canonical mission should be deferred in auto mode")

    monkeypatch.setattr(speak_routes.BRAIN_MISSION_SERVICE, "start", mission_must_not_run)

    retrieval, _continuum, _climate, mission, mission_error, casual = (
        speak_routes._run_governed_turn(
            owner="owner",
            conversation_id="conversation",
            project_id="project",
            message="Conduct a formal evidence review of wet winter orchid management.",
            research_mode="auto",
            retrieval_limit=8,
        )
    )

    assert casual is False
    assert mission is None
    assert mission_error is None
    assert retrieval["conversation_synthesis_mode"] == "general_knowledge_with_retrieval_gap"
    assert retrieval["canonical_mission_deferred"] is True
    assert "zero sources" in retrieval["canonical_mission_deferred_reason"]
