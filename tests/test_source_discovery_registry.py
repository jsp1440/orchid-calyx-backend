"""Tests for OC-COMPLETE-004 source discovery registry.

Proves acceptance criteria:
- registry covers all 5 required domains (literature, pollination, mycorrhizal, traits, media)
- every candidate record has all required per-candidate fields
- every decision is KEEP/ADD/DEFER/REJECT
- ADD candidates have child task specs with priority
- sensitive locality risk documented for every candidate
- GloBI is KEEP (not duplicated)
- registry is machine-readable JSON
- graph_mutation=False, automatic_publication=False
"""

from __future__ import annotations

import json

from app.scientific_adapter_lab.source_discovery_registry import (
    SOURCE_CANDIDATES,
    get_add_candidates,
    get_child_task_specs,
    get_source_registry,
    get_sources_by_decision,
    get_sources_by_domain,
    serialize_registry_as_json,
)

REQUIRED_FIELDS = {
    "source_id",
    "display_name",
    "domain",
    "owner",
    "url",
    "access_method",
    "license_terms",
    "data_scope",
    "update_cadence",
    "identifiers",
    "overlap_with_existing",
    "expected_incremental_value",
    "taxon_reconciliation_strategy",
    "provenance_contract",
    "sensitive_locality_risk",
    "implementation_cost",
    "decision",
    "decision_rationale",
}
VALID_DECISIONS = {"KEEP", "ADD", "DEFER", "REJECT"}
REQUIRED_DOMAINS = {"literature", "pollination", "mycorrhizal", "traits", "media"}
CHILD_TASK_PRIORITIES = {"P1", "P2", "P3", None}


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


def test_registry_has_at_least_ten_candidates():
    assert len(SOURCE_CANDIDATES) >= 10


def test_registry_covers_all_five_required_domains():
    domains = {s["domain"] for s in SOURCE_CANDIDATES}
    assert REQUIRED_DOMAINS <= domains, f"Missing domains: {REQUIRED_DOMAINS - domains}"


def test_every_candidate_has_required_fields():
    for candidate in SOURCE_CANDIDATES:
        missing = REQUIRED_FIELDS - set(candidate)
        assert not missing, f"{candidate['source_id']} missing: {missing}"


def test_every_decision_is_valid():
    for candidate in SOURCE_CANDIDATES:
        assert candidate["decision"] in VALID_DECISIONS, (
            f"{candidate['source_id']} has invalid decision: {candidate['decision']}"
        )


def test_no_duplicate_source_ids():
    ids = [c["source_id"] for c in SOURCE_CANDIDATES]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# Domain coverage
# ---------------------------------------------------------------------------


def test_literature_domain_has_at_least_two_candidates():
    lit = get_sources_by_domain("literature")
    assert len(lit) >= 2


def test_pollination_domain_has_at_least_two_candidates():
    poll = get_sources_by_domain("pollination")
    assert len(poll) >= 2


def test_mycorrhizal_domain_has_at_least_two_candidates():
    myco = get_sources_by_domain("mycorrhizal")
    assert len(myco) >= 2


def test_traits_domain_has_at_least_two_candidates():
    traits = get_sources_by_domain("traits")
    assert len(traits) >= 2


def test_media_domain_has_at_least_two_candidates():
    media = get_sources_by_domain("media")
    assert len(media) >= 2


# ---------------------------------------------------------------------------
# GloBI KEEP (not duplicated)
# ---------------------------------------------------------------------------


def test_globi_is_keep():
    globi = next(
        (s for s in SOURCE_CANDIDATES if "globi" in s["source_id"].lower() and s["domain"] == "pollination"),
        None,
    )
    assert globi is not None, "GloBI pollination entry not found"
    assert globi["decision"] == "KEEP"


def test_globi_keep_has_no_child_task():
    globi = next(s for s in SOURCE_CANDIDATES if s["source_id"] == "globi_pollination")
    assert globi.get("child_task_title") is None


# ---------------------------------------------------------------------------
# ADD candidates and child tasks
# ---------------------------------------------------------------------------


def test_at_least_six_add_candidates():
    add = get_add_candidates()
    assert len(add) >= 6


def test_every_add_candidate_has_child_task_title():
    for candidate in get_add_candidates():
        assert candidate.get("child_task_title"), (
            f"{candidate['source_id']} is ADD but has no child_task_title"
        )


def test_every_add_candidate_has_valid_child_task_priority():
    for candidate in get_add_candidates():
        assert candidate.get("child_task_priority") in CHILD_TASK_PRIORITIES, (
            f"{candidate['source_id']} has invalid priority: {candidate.get('child_task_priority')}"
        )


def test_child_task_specs_have_all_required_fields():
    specs = get_child_task_specs()
    assert len(specs) >= 6
    for spec in specs:
        assert spec.get("source_id")
        assert spec.get("title")
        assert spec.get("priority") in {"P1", "P2", "P3"}
        assert spec.get("domain")


def test_add_candidates_span_multiple_domains():
    add = get_add_candidates()
    domains = {s["domain"] for s in add}
    assert len(domains) >= 3


# ---------------------------------------------------------------------------
# Locality risk documentation
# ---------------------------------------------------------------------------


def test_every_candidate_has_sensitive_locality_risk_documented():
    for candidate in SOURCE_CANDIDATES:
        risk = candidate.get("sensitive_locality_risk") or ""
        assert risk, f"{candidate['source_id']} has no sensitive_locality_risk"


def test_inat_has_high_locality_risk():
    inat = next(s for s in SOURCE_CANDIDATES if s["source_id"] == "inat_pollination")
    assert "HIGH" in inat["sensitive_locality_risk"]


def test_gbif_occurrence_has_high_locality_risk():
    gbif = next(s for s in SOURCE_CANDIDATES if s["source_id"] == "gbif_occurrence")
    assert "HIGH" in gbif["sensitive_locality_risk"]


# ---------------------------------------------------------------------------
# DEFER candidates
# ---------------------------------------------------------------------------


def test_defer_candidates_have_decision_rationale():
    for candidate in get_sources_by_decision("DEFER"):
        assert candidate["decision_rationale"], f"{candidate['source_id']} DEFER has no rationale"


def test_mycoflor_is_defer_not_add():
    mycoflor = next(s for s in SOURCE_CANDIDATES if s["source_id"] == "mycoflor")
    assert mycoflor["decision"] == "DEFER"


def test_try_traits_is_defer():
    try_entry = next(s for s in SOURCE_CANDIDATES if s["source_id"] == "try_traits")
    assert try_entry["decision"] == "DEFER"


# ---------------------------------------------------------------------------
# Machine-readable report
# ---------------------------------------------------------------------------


def test_registry_schema_version():
    registry = get_source_registry()
    assert registry["schema_version"] == "oc-source-discovery-registry/v1"


def test_registry_graph_mutation_false():
    registry = get_source_registry()
    assert registry["graph_mutation"] is False


def test_registry_automatic_publication_false():
    registry = get_source_registry()
    assert registry["automatic_publication"] is False


def test_registry_serializable_as_json():
    raw = serialize_registry_as_json()
    parsed = json.loads(raw)
    assert parsed["source_count"] == len(SOURCE_CANDIDATES)


def test_get_sources_by_decision_add():
    add = get_sources_by_decision("ADD")
    assert all(s["decision"] == "ADD" for s in add)


def test_get_sources_by_decision_keep():
    keep = get_sources_by_decision("KEEP")
    assert all(s["decision"] == "KEEP" for s in keep)
