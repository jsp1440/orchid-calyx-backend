import pytest

from app.canonical_brain.priority_batch_three import (
    ArchitectureChangeProposal,
    CareEvent,
    ConservatoryTimeline,
    EventRouter,
    ExplorerConcept,
    HabitatVariable,
    KnowledgeExplorerIndex,
    ProtocolStep,
    ReportSection,
    ResearchProtocol,
    RiskItem,
    TaxonCandidate,
    VisionReviewItem,
    VisionReviewQueue,
    assemble_report,
    calculate_habitat_suitability,
    propose_architecture_change,
    rank_taxa,
    summarize_risks,
)


def test_knowledge_explorer_search_and_learning_path_are_deterministic() -> None:
    index = KnowledgeExplorerIndex([
        ExplorerConcept(concept_id="root", label="Orchid root", evidence_ids=["ev:1"]),
        ExplorerConcept(concept_id="velamen", label="Velamen", aliases=["velamen radicum"], prerequisite_ids=["root"], evidence_ids=["ev:2"]),
        ExplorerConcept(concept_id="passage-cell", label="Passage cell", prerequisite_ids=["velamen"], evidence_ids=["ev:3"]),
    ])
    assert [item.concept_id for item in index.search("velamen")] == ["velamen"]
    assert index.learning_path("passage-cell") == ["root", "velamen", "passage-cell"]


def test_knowledge_explorer_rejects_unknown_relationships() -> None:
    with pytest.raises(ValueError, match="unknown concept reference"):
        KnowledgeExplorerIndex([ExplorerConcept(concept_id="velamen", label="Velamen", related_ids=["missing"], evidence_ids=["ev:1"])])


def test_habitat_suitability_is_weighted_and_candidate_only() -> None:
    result = calculate_habitat_suitability("taxon:1", "h3:abc", [
        HabitatVariable(variable_id="temperature", normalized_score=0.8, evidence_id="ev:t", weight=2),
        HabitatVariable(variable_id="rainfall", normalized_score=0.5, evidence_id="ev:r", weight=1),
    ])
    assert result.suitability_score == 0.7
    assert result.status == "candidate"
    assert result.evidence_ids == ["ev:r", "ev:t"]


def test_research_protocol_checksum_is_repeatable() -> None:
    protocol = ResearchProtocol(protocol_id="protocol:1", title="Root anatomy review", version="1", steps=[ProtocolStep(step_id="s1", instruction="Review evidence")], source_uris=["doi:example"])
    assert protocol.reproducibility_checksum() == protocol.reproducibility_checksum()


def test_conservatory_timeline_orders_events_and_rejects_conflicts() -> None:
    timeline = ConservatoryTimeline()
    timeline.register(CareEvent(event_id="e2", specimen_id="s1", event_type="watered", occurred_at="2026-08-02"))
    timeline.register(CareEvent(event_id="e1", specimen_id="s1", event_type="repotted", occurred_at="2026-08-01", sensor_snapshot_id="sensor:1"))
    assert [item.event_id for item in timeline.for_specimen("s1")] == ["e1", "e2"]
    with pytest.raises(ValueError, match="conflicting care event"):
        timeline.register(CareEvent(event_id="e1", specimen_id="s1", event_type="moved", occurred_at="2026-08-01"))


def test_matrix_ranking_separates_matches_conflicts_and_missing() -> None:
    ranked = rank_taxa({"leaf": "thick", "flower": "white"}, [
        TaxonCandidate(taxon_id="taxon:a", states={"leaf": "thick", "flower": "white"}),
        TaxonCandidate(taxon_id="taxon:b", states={"leaf": "thin", "flower": None}),
    ])
    assert ranked[0].taxon_id == "taxon:a"
    assert ranked[0].matched == 2
    assert ranked[1].conflicting == 1
    assert ranked[1].missing == 1


def test_vision_review_queue_is_terminal_after_decision() -> None:
    queue = VisionReviewQueue()
    queue.submit(VisionReviewItem(observation_id="obs:1", image_id="img:1", proposed_character_id="char:1", proposed_state="present", confidence=0.8))
    approved = queue.decide("obs:1", "approved")
    assert approved.status == "approved"
    with pytest.raises(ValueError, match="terminal"):
        queue.decide("obs:1", "rejected")


def test_report_assembly_is_deterministic_and_unpublished() -> None:
    sections = [
        ReportSection(section_id="b", title="Methods", body="Method text", evidence_ids=["ev:2"]),
        ReportSection(section_id="a", title="Summary", body="Summary text", evidence_ids=["ev:1"]),
    ]
    first = assemble_report("report:1", "Report", sections)
    second = assemble_report("report:1", "Report", list(reversed(sections)))
    assert first.checksum == second.checksum
    assert [section.section_id for section in first.sections] == ["a", "b"]
    assert first.publication_enabled is False


def test_event_router_is_idempotent_and_rejects_unrouted_events() -> None:
    router = EventRouter({"specimen.updated": ["brain", "conservatory", "brain"]})
    first = router.route("event:1", "specimen.updated", "conservatory", {"specimen_id": "s1"})
    second = router.route("event:1", "specimen.updated", "conservatory", {"specimen_id": "s1"})
    assert first == second
    assert first.destinations == ["brain", "conservatory"]
    with pytest.raises(ValueError, match="no route"):
        router.route("event:2", "unknown", "test", {})


def test_mission_control_risk_summary_excludes_mitigated_risks() -> None:
    summary = summarize_risks([
        RiskItem(risk_id="r1", architecture_id="atlas", severity="critical", blocker_build_ids=["b2", "b1"]),
        RiskItem(risk_id="r2", architecture_id="brain", severity="high", status="mitigated", blocker_build_ids=["b3"]),
    ])
    assert summary.open_count == 1
    assert summary.critical_count == 1
    assert summary.blocked_build_ids == ["b1", "b2"]


def test_architecture_change_capture_is_stable_and_proposed_only() -> None:
    first = propose_architecture_change("Add Earth science", ["architecture:atlas"], "Explain orchid distributions.", "conversation://1", ["decision", "architecture"])
    second = propose_architecture_change("Add Earth science", ["architecture:atlas"], "Explain orchid distributions.", "conversation://1", ["architecture", "decision"])
    assert isinstance(first, ArchitectureChangeProposal)
    assert first.proposal_id == second.proposal_id
    assert first.status == "proposed"
    assert first.proposed_object_types == ["architecture", "decision"]
