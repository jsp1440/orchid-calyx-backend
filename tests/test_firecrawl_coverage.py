"""Coverage remains acquisition status, never scientific consensus."""
from types import SimpleNamespace

import pytest

from app.literature_extraction.coverage_audit import (
    export_matrix_acquisition_coverage as export_coverage,
)
from runtime.knowledge_graph.canonical_taxonomy import (
    CanonicalRegistry,
    CanonicalTaxon,
    WorldPlantsRelease,
)
from runtime.knowledge_graph.firecrawl_taxonomy import (
    load_persistent_canonical_registry,
)
from scripts.oc_work_discovery import discover_matrix_coverage


def export_matrix_acquisition_coverage(*args, **kwargs):
    return export_coverage(*args, required_predicates=("leaf_length",), **kwargs)


def registry():
    taxa = {
        number: CanonicalTaxon(number, name, name, None, "species", "accepted", False,
                               provenance={"identity_namespace": "orchid_taxonomy"})
        for number, name in ((701, "Paphiopedilum delenatii"), (799, "Paphiopedilum armeniacum"),
                             (801, "Cattleya labiata"))
    }
    release = WorldPlantsRelease("release-1", "world_plants", "fixture", "a" * 64, 3, None)
    return CanonicalRegistry(release, taxa, {taxon.canonical_name: ident for ident, taxon in taxa.items()})


def coverage_repository(*, snapshot="release-1", anchors=(4,), subject="local:orchid_taxonomy:701", state="COMPLETED"):
    candidate = SimpleNamespace(metadata={"taxonomy_snapshot": snapshot}, predicate="leaf_length",
                                source_anchor_ids=anchors, document_hash="b" * 64, normalized_subject=subject)
    return SimpleNamespace(refresh=lambda: None, runs={1: {"state": state}},
                           items={1: [{"candidates": [candidate]}]})


def test_current_anchored_acquisition_drives_genus_work_without_publishing():
    report = export_matrix_acquisition_coverage(registry(), coverage_repository())
    assert report["covered_taxa"] == 1
    assert report["gaps"][0]["missing_taxon_ids"] == [799]
    candidate, = discover_matrix_coverage(report)
    assert "OC-ACQUISITION-GENUS: Paphiopedilum" in candidate.summary
    assert report["scientific_publication"] is False


@pytest.mark.parametrize("settings", [
    {"snapshot": "stale"}, {"anchors": ()}, {"state": "PARTIAL"},
    {"subject": "local:world_plants:701"},
])
def test_unbound_or_incomplete_evidence_does_not_hide_gaps(settings):
    report = export_matrix_acquisition_coverage(registry(), coverage_repository(**settings))
    assert report["covered_taxa"] == 0
    assert report["gaps"][0]["missing_taxon_ids"] == [701, 799]


def test_pilot_genus_is_configurable_and_general_discovery_is_bounded():
    report = export_matrix_acquisition_coverage(registry(), coverage_repository(), pilot_genus="Cattleya")
    assert [gap["genus"] for gap in report["gaps"]] == ["Cattleya"]
    report = export_matrix_acquisition_coverage(registry(), coverage_repository(anchors=()), pilot_mode=False, max_genera=1)
    assert [gap["genus"] for gap in report["gaps"]] == ["Paphiopedilum"]
    assert report["remaining_genus_gaps"] == 1


def test_taxonomy_requires_explicit_source_selection(monkeypatch):
    monkeypatch.delenv("FIRECRAWL_TAXONOMY_SNAPSHOT_ID", raising=False)
    with pytest.raises(ValueError, match="PINNED_CANONICAL"):
        load_persistent_canonical_registry(lambda: pytest.fail("must fail before database access"))


def test_targeted_species_followup_requires_prior_genus_evidence():
    first = export_matrix_acquisition_coverage(registry(), coverage_repository(anchors=()))
    assert first["gaps"][0]["strategy"] == "genus-source-first"
    assert "target_taxon_names" not in first["gaps"][0]
    followup = export_matrix_acquisition_coverage(registry(), coverage_repository())
    assert followup["gaps"][0]["strategy"] == "targeted-species-gap"
    assert followup["gaps"][0]["target_taxon_names"] == ["Paphiopedilum armeniacum"]
    candidate, = discover_matrix_coverage(followup)
    assert 'OC-ACQUISITION-TARGETS: ["Paphiopedilum armeniacum"]' in candidate.summary


def test_targeted_species_from_another_genus_are_rejected():
    report = export_matrix_acquisition_coverage(registry(), coverage_repository())
    report["gaps"][0]["target_taxon_names"] = ["Cattleya labiata"]
    with pytest.raises(ValueError, match="INVALID_MATRIX_GAP_TARGETS"):
        discover_matrix_coverage(report)


def test_unconfigured_matrix_requirements_do_not_invent_gaps():
    report = export_coverage(registry(), coverage_repository())
    assert not report["available"] and report["gaps"] == []
    assert report["reason"] == "MATRIX_PREDICATE_REQUIREMENTS_UNCONFIGURED"


def test_predicate_gap_is_explicit_and_not_any_morphology_coverage():
    report = export_coverage(registry(), coverage_repository(), required_predicates=("leaf_length", "petal_width"))
    gap = report["gaps"][0]
    assert gap["missing_predicates_by_taxon"]["701"] == ["petal_width"]
    assert report["covered_taxa"] == 0
    candidate, = discover_matrix_coverage(report)
    assert 'OC-ACQUISITION-PREDICATES: ["leaf_length", "petal_width"]' in candidate.summary


def test_hosted_coverage_prioritizes_observed_reuse_with_paid_provider_disabled(monkeypatch):
    from app.evidence_aggregation import postgres_repository
    from app.literature_extraction import corpus_audit, routes
    from runtime.knowledge_graph import firecrawl_taxonomy

    monkeypatch.setenv("FIRECRAWL_ENABLED", "false")
    monkeypatch.setenv("FIRECRAWL_PILOT_MODE", "false")
    monkeypatch.setenv("FIRECRAWL_REQUIRED_PREDICATES", "leaf_length")
    monkeypatch.setattr(firecrawl_taxonomy, "load_persistent_canonical_registry", lambda _: registry())
    monkeypatch.setattr(postgres_repository, "PostgresAggregateRepository", lambda _: coverage_repository(anchors=()))
    audited = []

    def audit(_connect, *, genus, taxon_names):
        audited.append(genus)
        assert all(name.startswith(genus + " ") for name in taxon_names)
        return {"available": True, "audit_complete": True, "complete": True,
                "documents": [{"loadable": True}] if genus == "Cattleya" else []}

    monkeypatch.setattr(corpus_audit, "audit_existing_corpus", audit)
    report = routes.canonical_acquisition_coverage(_auth={})
    assert set(audited) == {"Paphiopedilum", "Cattleya"}
    assert report["gaps"][0]["genus"] == "Cattleya"
    assert report["gaps"][0]["held_sources_ready_for_reuse"] == 1
    assert report["gaps"][1]["held_sources_ready_for_reuse"] == 0
