"""Coverage remains acquisition status, never scientific consensus."""
from types import SimpleNamespace

import pytest

from app.literature_extraction.coverage_audit import export_matrix_acquisition_coverage
from runtime.knowledge_graph.canonical_taxonomy import (
    CanonicalRegistry,
    CanonicalTaxon,
    WorldPlantsRelease,
)
from runtime.knowledge_graph.firecrawl_taxonomy import (
    load_persistent_canonical_registry,
)
from scripts.oc_work_discovery import discover_matrix_coverage


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
