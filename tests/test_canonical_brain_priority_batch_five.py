from datetime import datetime, timezone

import pytest

from app.canonical_brain.priority_batch_five import (
    AnalysisInput,
    ApprovalQueueItem,
    CandidateProfile,
    ConservationFactor,
    DeadLetterQueue,
    DiscoveryDocument,
    GlossaryMedia,
    LabelRecord,
    MorphologyCandidate,
    TemplateSection,
    build_analysis_manifest,
    build_discovery_index_manifest,
    build_glossary_card,
    build_morphology_candidates,
    build_publication_template,
    calculate_conservation_priority,
    eliminate_candidates,
    project_approvals,
    stage_label_print_job,
)


def test_glossary_card_is_deterministic_and_multimedia() -> None:
    media = [GlossaryMedia(media_id="m1", media_type="illustration", source_uri="brain://figures/velamen", license="CC-BY", alt_text="Velamen layers", evidence_ids=["ev1"])]
    first = build_glossary_card("concept:velamen", "Velamen", "A multilayered root covering.", "A specialized multilayered epidermal structure of many orchid roots.", ["radicum velamen"], ["concept:exodermis"], media, ["ev1"])
    second = build_glossary_card("concept:velamen", "Velamen", "A multilayered root covering.", "A specialized multilayered epidermal structure of many orchid roots.", ["radicum velamen"], ["concept:exodermis"], media, ["ev1"])
    assert first.checksum == second.checksum
    assert first.status == "candidate"
    with pytest.raises(ValueError):
        build_glossary_card("c", "x", "", "expanded", [], [], [], ["ev1"])


def test_conservation_priority_is_weighted_and_candidate_only() -> None:
    result = calculate_conservation_priority("taxon:1", [ConservationFactor(factor_id="threat", normalized_score=1.0, weight=2, evidence_id="e1"), ConservationFactor(factor_id="protection_gap", normalized_score=0.5, weight=1, evidence_id="e2")])
    assert result.priority_score == pytest.approx(0.83333333)
    assert result.status == "candidate"


def test_analysis_manifest_rejects_duplicate_inputs_and_is_repeatable() -> None:
    inputs = [AnalysisInput(artifact_id="a1", checksum="a" * 64)]
    first = build_analysis_manifest("analysis:1", "git://repo@sha", "container://python312", inputs, {"alpha": 0.05})
    second = build_analysis_manifest("analysis:1", "git://repo@sha", "container://python312", inputs, {"alpha": 0.05})
    assert first.checksum == second.checksum
    assert not first.execution_enabled
    with pytest.raises(ValueError):
        build_analysis_manifest("analysis:2", "code", "env", inputs + inputs, {})


def test_label_job_is_staged_and_rejects_duplicate_specimens() -> None:
    labels = [LabelRecord(specimen_id="s1", accession_number="A-1", display_name="Cattleya", qr_payload="orchid://specimen/s1")]
    job = stage_label_print_job("job:1", labels, "template:brother")
    assert job.status == "staged"
    with pytest.raises(ValueError):
        stage_label_print_job("job:2", labels + labels, "template:brother")


def test_matrix_elimination_explains_conflicts() -> None:
    candidates = [CandidateProfile(taxon_id="t1", states={"lip": {"three-lobed"}}), CandidateProfile(taxon_id="t2", states={"lip": {"entire"}})]
    remaining, eliminated = eliminate_candidates(candidates, {"lip": "three-lobed"})
    assert remaining == ["t1"]
    assert eliminated == {"t2": ["lip"]}


def test_morphology_candidates_are_unique_and_ranked() -> None:
    items = [MorphologyCandidate(observation_id="o1", image_id="i1", structure="root", character_id="velamen_layers", proposed_state="multiple", confidence=0.8, evidence_region_id="r1"), MorphologyCandidate(observation_id="o2", image_id="i1", structure="root", character_id="root_shape", proposed_state="terete", confidence=0.9, evidence_region_id="r2")]
    assert [item.observation_id for item in build_morphology_candidates(items)] == ["o2", "o1"]
    with pytest.raises(ValueError):
        build_morphology_candidates(items + [items[0]])


def test_publication_template_keeps_publication_disabled() -> None:
    template = build_publication_template("template:conservation", "Conservation Report", [TemplateSection(section_id="summary", title="Summary", required_evidence_classes=["occurrence"]), TemplateSection(section_id="threats", title="Threats", required_evidence_classes=["threat"] )])
    assert template.section_order == ["summary", "threats"]
    assert not template.publication_enabled


def test_dead_letter_queue_is_idempotent_and_timezone_safe() -> None:
    queue = DeadLetterQueue()
    now = datetime(2026, 8, 6, 21, 0, tzinfo=timezone.utc)
    first = queue.record("event:1", "atlas.updated", "no consumer", {"x": 1}, now)
    second = queue.record("event:1", "atlas.updated", "no consumer", {"x": 1}, now)
    assert first == second
    assert queue.open_records() == [first]
    with pytest.raises(ValueError):
        queue.record("event:2", "x", "reason", {}, datetime(2026, 8, 6, 21, 0))


def test_approval_projection_lists_missing_review_classes() -> None:
    projection = project_approvals([ApprovalQueueItem(item_id="item:1", architecture_id="atlas", review_classes=["scientific", "licensing"], completed_review_classes=["scientific"]), ApprovalQueueItem(item_id="item:2", architecture_id="brain", review_classes=["security"], completed_review_classes=["security"])])
    assert projection.ready_ids == ["item:2"]
    assert projection.waiting_ids == ["item:1"]
    assert projection.missing_reviews == {"item:1": ["licensing"]}


def test_discovery_manifest_is_deterministic_and_provider_disabled() -> None:
    docs = [DiscoveryDocument(object_id="arch:atlas", title="Atlas", text="Planetary intelligence and thematic mapping", aliases=["Earth Systems Atlas"], tags=["maps"], source_uri="brain://architecture/atlas")]
    first = build_discovery_index_manifest("index:brain", docs)
    second = build_discovery_index_manifest("index:brain", docs)
    assert first.checksum == second.checksum
    assert not first.provider_enabled
