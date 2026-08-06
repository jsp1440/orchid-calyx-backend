from datetime import datetime, timezone

import pytest

from app.canonical_brain.priority_batch_eight import (
    ArticleSection,
    ArchitectureDependency,
    CharacterPartition,
    DamageObservationCandidate,
    DataQualityCheck,
    EnvironmentalReading,
    GlossaryCoverageItem,
    PortfolioMetricSnapshot,
    RestorationSiteCandidate,
    RetryPolicy,
    analyze_dependency_impact,
    assemble_article,
    audit_glossary_coverage,
    build_data_quality_manifest,
    compare_portfolio_snapshots,
    evaluate_environmental_reading,
    rank_character_information,
    rank_damage_observations,
    rank_restoration_sites,
)


def test_glossary_coverage_audit() -> None:
    summary = audit_glossary_coverage([
        GlossaryCoverageItem(concept_id="velamen", has_definition=True, has_evidence=True, has_accessible_media=True, has_related_concepts=True),
        GlossaryCoverageItem(concept_id="passage-cell", has_definition=True, has_evidence=False, has_accessible_media=True, has_related_concepts=True),
    ])
    assert summary.complete_ids == ["velamen"]
    assert summary.incomplete_ids == ["passage-cell"]
    assert summary.coverage_ratio == 0.5


def test_restoration_ranking_is_deterministic() -> None:
    ranked = rank_restoration_sites([
        RestorationSiteCandidate(site_id="b", habitat_suitability=0.8, conservation_priority=0.9, restoration_feasibility=0.4, threat_reduction_potential=0.5, evidence_ids=["e2"]),
        RestorationSiteCandidate(site_id="a", habitat_suitability=0.9, conservation_priority=0.9, restoration_feasibility=0.8, threat_reduction_potential=0.7, evidence_ids=["e1"]),
    ])
    assert [item.site_id for item in ranked] == ["a", "b"]
    assert all(item.status == "candidate" for item in ranked)


def test_data_quality_manifest_rejects_duplicate_checks() -> None:
    check = DataQualityCheck(check_id="c1", category="validity", passed=True, evidence_ids=["e1"], message="ok")
    with pytest.raises(ValueError):
        build_data_quality_manifest("dataset", [check, check])


def test_environmental_alert_boundary() -> None:
    alert = evaluate_environmental_reading(EnvironmentalReading(
        reading_id="r1", specimen_id="s1", variable="temperature", value=40,
        observed_at=datetime.now(timezone.utc), minimum=15, maximum=30,
    ))
    assert alert is not None
    assert alert.severity == "critical"


def test_character_information_prefers_better_partition() -> None:
    ranked = rank_character_information([
        CharacterPartition(character_id="weak", state_to_taxa={"x": ["a", "b", "c"]}),
        CharacterPartition(character_id="strong", state_to_taxa={"x": ["a"], "y": ["b"], "z": ["c"]}),
    ])
    assert ranked[0].character_id == "strong"


def test_damage_observation_duplicates_fail_closed() -> None:
    item = DamageObservationCandidate(observation_id="o1", image_id="i1", region_id="r1", category="pest", confidence=0.8, evidence_ids=["e1"])
    with pytest.raises(ValueError):
        rank_damage_observations([item, item])


def test_article_assembly_is_unpublished() -> None:
    article = assemble_article("a1", "Title", [ArticleSection(section_id="s1", heading="H", body="B", evidence_ids=["e1"])])
    assert article.publication_enabled is False
    assert len(article.checksum) == 64


def test_retry_policy_is_bounded() -> None:
    policy = RetryPolicy(policy_id="p1", maximum_attempts=3, base_delay_seconds=10, maximum_delay_seconds=25)
    assert [policy.delay_for_attempt(i) for i in (1, 2, 3)] == [10, 20, 25]
    with pytest.raises(ValueError):
        policy.delay_for_attempt(4)


def test_portfolio_snapshots_require_chronology() -> None:
    now = datetime.now(timezone.utc)
    snapshot = PortfolioMetricSnapshot(snapshot_id="x", observed_at=now, admitted=1, running=1, blocked=0, completed=0)
    with pytest.raises(ValueError):
        compare_portfolio_snapshots(snapshot, snapshot)


def test_dependency_impact_traverses_reverse_edges() -> None:
    report = analyze_dependency_impact("brain", [
        ArchitectureDependency(source_id="mission-control", target_id="brain"),
        ArchitectureDependency(source_id="atlas", target_id="mission-control"),
    ])
    assert report.directly_affected_ids == ["mission-control"]
    assert report.transitively_affected_ids == ["atlas", "mission-control"]
