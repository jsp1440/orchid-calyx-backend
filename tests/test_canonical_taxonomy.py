"""BUILD-065 tests: canonical taxonomy resolution, World Plants supersession,
synonym resolution, authority mapping, crosswalk classification, conflict
detection and controlled graph activation.

No test opens a database connection. Registry logic is exercised against rows
shaped exactly like the production projections; activation is exercised against
the in-memory orchestrator (staging graph, never production).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from runtime.knowledge_graph import (
    ACTIVATED_DOMAINS,
    CANONICAL_AUTHORITY_LABEL,
    WITHHELD_DOMAINS,
    BuildOrchestrator,
    ExecutionMode,
    InMemoryCheckpointStore,
    InMemoryGraphRepository,
    InMemorySourceProvider,
    WorldPlantsRelease,
    build_canonical_registry,
    classify_crosswalk,
    classify_mapping,
    detect_conflicts,
    select_canonical_release,
)
from runtime.knowledge_graph.canonical_taxonomy import (
    AUTO_PUBLISHABLE_MAPPINGS,
    MAP_ACCEPTED_NAME,
    MAP_AUTHORITY_SYNONYM,
    MAP_EXACT_ID,
    MAP_HISTORICAL,
    MAP_MANUAL_REVIEW,
    RELEASE_CANONICAL,
    RELEASE_HISTORICAL,
    RELEASE_SUPERSEDED,
    canonical_name_of,
    is_hybrid,
    rank_of,
)


def _rel(sid, label, sha, rows, day, system="world_plants"):
    return WorldPlantsRelease(
        snapshot_id=sid, source_system=system, version_label=label,
        file_sha256=sha, row_count=rows, acquired_at=datetime(2026, 2, day),
    )


# --- version selection / supersession ---------------------------------------

def test_newest_world_plants_release_is_canonical():
    r_old = _rel("a", "2026-01", "sha_old", 34000, 10)
    r_new = _rel("b", "2026-02", "sha_new", 34602, 24)
    canonical, allr = select_canonical_release([r_old, r_new])
    assert canonical.snapshot_id == "b"
    by_id = {r.snapshot_id: r.status for r in allr}
    assert by_id["b"] == RELEASE_CANONICAL
    assert by_id["a"] == RELEASE_HISTORICAL


def test_same_file_sha_is_superseded_not_historical():
    # Same file registered twice -> newer is canonical, older same-SHA superseded.
    r1 = _rel("a", "Hassler_2026-02", "same", 34602, 24)
    r2 = _rel("b", "2026-02", "same", 34602, 26)
    canonical, allr = select_canonical_release([r1, r2])
    by_id = {r.snapshot_id: r.status for r in allr}
    assert by_id["b"] == RELEASE_CANONICAL
    assert by_id["a"] == RELEASE_SUPERSEDED


def test_non_world_plants_release_never_canonical():
    powo = _rel("p", "powo", "x", 50000, 28, system="powo")
    wp = _rel("w", "2026-02", "y", 34602, 24)
    canonical, _ = select_canonical_release([powo, wp])
    assert canonical.snapshot_id == "w"


def test_no_eligible_release_returns_none():
    canonical, allr = select_canonical_release(
        [_rel("z", "empty", "s", 0, 24)]
    )
    assert canonical is None
    assert all(r.status == RELEASE_HISTORICAL for r in allr)


def test_null_row_count_still_eligible():
    canonical, _ = select_canonical_release([_rel("a", "2026-02", "s", None, 24)])
    assert canonical is not None and canonical.snapshot_id == "a"


# --- name / rank / hybrid helpers -------------------------------------------

def test_canonical_name_strips_authorship_and_entities():
    assert canonical_name_of("Lepanthes vulpina Luer &amp; Sijm") == "Lepanthes vulpina"
    assert canonical_name_of("Aa Rchb.f.") == "Aa"


def test_rank_codes():
    assert rank_of("S") == "species"
    assert rank_of("G") == "genus"
    assert rank_of("SS") == "subspecies"
    assert rank_of("ZZ") == "unknown"


def test_hybrid_detection():
    assert is_hybrid("Cattleya × hybrida")
    assert not is_hybrid("Cattleya labiata")


# --- registry construction / synonym resolution -----------------------------

LOAD = [
    {"name": "Cattleya labiata Lindl.", "taxon_code": "S"},
    {"name": "Cattleya warscewiczii Rchb.f.", "taxon_code": "S"},
    {"name": "Cattleya × hybrida Hort.", "taxon_code": "S"},
]
SYN = [
    {"input_match_name": "Cattleya gigas", "accepted_match_name": "Cattleya warscewiczii",
     "input_name": "Cattleya gigas Linden & André", "relationship": "synonym"},
    {"input_match_name": "Cattleya warscewiczii", "accepted_match_name": "Cattleya warscewiczii",
     "input_name": "Cattleya warscewiczii Rchb.f.", "relationship": "accepted"},
]
AUTH = [
    {"canonical_name": "Cattleya labiata", "authority": "gbif", "external_id": "123", "confidence": 1.0},
    {"canonical_name": "Cattleya labiata", "authority": "POWO", "external_id": "p1", "confidence": 0.98},
]


def _registry():
    return build_canonical_registry(LOAD, SYN, AUTH)


def test_registry_dedupes_and_counts():
    reg = _registry()
    assert len(reg.accepted()) == 3
    assert reg.summary()["canonical_authority"] == CANONICAL_AUTHORITY_LABEL


def test_synonym_points_to_accepted():
    reg = _registry()
    resolved = reg.resolve("Cattleya gigas")
    assert resolved is not None
    assert resolved.canonical_name == "Cattleya warscewiczii"
    assert resolved.status == "accepted"


def test_synonym_resolution_follows_from_authorship_name():
    reg = _registry()
    assert reg.resolve("Cattleya gigas Linden & André").canonical_name == "Cattleya warscewiczii"


def test_hybrid_flagged_in_registry():
    reg = _registry()
    assert any(t.is_hybrid for t in reg.accepted())


def test_authority_mappings_attached_not_duplicated_as_taxa():
    reg = _registry()
    labiata = reg.resolve("Cattleya labiata")
    authorities = {m.authority for m in labiata.authority_mappings}
    assert authorities == {"GBIF", "POWO"}
    # authorities do NOT create their own taxa
    assert len(reg.accepted()) == 3


def test_orphan_synonym_skipped_when_accepted_absent():
    reg = build_canonical_registry(
        LOAD,
        [{"input_match_name": "Foo bar", "accepted_match_name": "Nonexistent taxon",
          "relationship": "synonym"}],
    )
    assert reg.resolve("Foo bar") is None


# --- crosswalk classification ------------------------------------------------

def test_exact_id_mapping_auto_publishable():
    assert classify_mapping(
        {"method": "exact_match", "confidence": 1.0, "source_id": "1", "destination_id": "2"}
    ) == MAP_EXACT_ID


def test_id_plus_canonical_name_is_accepted_name_mapping():
    assert classify_mapping(
        {"method": "crosswalk_id+canonical_name", "confidence": "1.0",
         "authority": "orchid_continuum_taxon_crosswalk",
         "source_id": "1", "destination_id": "2"}
    ) == MAP_ACCEPTED_NAME


def test_low_confidence_is_manual_review():
    assert classify_mapping({"method": "fuzzy", "confidence": 0.4}) == MAP_MANUAL_REVIEW


def test_fuzzy_never_auto_publishable():
    assert MAP_MANUAL_REVIEW not in AUTO_PUBLISHABLE_MAPPINGS


def test_classify_crosswalk_aggregates():
    out = classify_crosswalk([
        {"method": "exact_match", "confidence": 1.0, "source_id": "1", "destination_id": "2"},
        {"method": "fuzzy", "confidence": 0.3},
    ])
    assert out["total"] == 2
    assert out["auto_publishable"] == 1
    assert out["requires_review"] == 1


# --- conflict detection ------------------------------------------------------

def test_duplicate_accepted_taxa_detected():
    reg = build_canonical_registry(
        [{"name": "Cattleya labiata Lindl.", "taxon_code": "S"}]
    )
    # inject a manual duplicate accepted taxon with the same canonical name
    from runtime.knowledge_graph.canonical_taxonomy import CanonicalTaxon
    reg.taxa[999] = CanonicalTaxon(
        canonical_id=999, scientific_name="Cattleya labiata Dup.",
        canonical_name="Cattleya labiata", authorship="Dup.", rank="species",
        status="accepted", is_hybrid=False,
    )
    conflicts = detect_conflicts(reg)
    assert len(conflicts["duplicate_accepted_taxa"]) == 1


def test_authority_disagreement_detected():
    reg = build_canonical_registry(
        LOAD, [],
        [
            {"canonical_name": "Cattleya labiata", "authority": "GBIF", "external_id": "1"},
            {"canonical_name": "Cattleya labiata", "authority": "GBIF", "external_id": "2"},
        ],
    )
    conflicts = detect_conflicts(reg)
    assert len(conflicts["authority_disagreements"]) == 1


# --- controlled graph activation --------------------------------------------

def test_activation_allowlist_matches_defensible_domains():
    assert ACTIVATED_DOMAINS == frozenset({"media", "traits", "pollinators", "occurrences"})
    for d in ("climate", "conservation", "mycorrhiza", "literature"):
        assert d in WITHHELD_DOMAINS
    assert not (ACTIVATED_DOMAINS & set(WITHHELD_DOMAINS))


def test_limited_population_activates_only_allowlisted_and_never_writes_prod():
    prod = InMemoryGraphRepository()
    src = InMemorySourceProvider({})
    orch = BuildOrchestrator(
        prod, src, checkpoint_store=InMemoryCheckpointStore(),
        activated_domains=ACTIVATED_DOMAINS,
    )
    report = orch.run(ExecutionMode.LIMITED_POPULATION)
    assert report["build"]["wrote_to_production"] is False
    assert len(prod.all_nodes()) == 0  # production untouched
    per = {o["domain"]: o for o in report["per_domain"]}
    for d in WITHHELD_DOMAINS:
        assert per[d]["status"] == "skipped"
    assert report["activation"]["applies"] is True
    assert set(report["activation"]["activated_domains"]) == set(ACTIVATED_DOMAINS)


def test_dry_run_ignores_activation_allowlist():
    # DRY_RUN validates the full graph; activation only gates LIMITED_POPULATION.
    prod = InMemoryGraphRepository()
    src = InMemorySourceProvider({})
    report = BuildOrchestrator(
        prod, src, activated_domains=ACTIVATED_DOMAINS,
    ).run(ExecutionMode.DRY_RUN)
    per = {o["domain"]: o for o in report["per_domain"]}
    assert per["climate"]["status"] != "skipped"


def test_limited_population_mode_exists():
    assert ExecutionMode.LIMITED_POPULATION.value == "limited_population"
