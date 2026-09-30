from app.evidence_federation import (
    adapt_iospe_row,
    adapt_yong_gee_row,
    compare_assertions,
    reconcile_source_record,
)
from runtime.knowledge_graph.canonical_taxonomy import build_canonical_registry


def _registry():
    return build_canonical_registry(
        [
            {"name": "Aa argyrolepis Rchb.f.", "taxon_code": "S"},
            {"name": "Bulbophyllum maxillare (Lindl.) Rchb.f.", "taxon_code": "S"},
        ],
        [
            {
                "input_match_name": "Ephippium ciliatum",
                "accepted_match_name": "Bulbophyllum maxillare",
                "input_name": "Ephippium ciliatum",
                "relationship": "synonym",
            }
        ],
    )


def test_iospe_adapter_preserves_marker_raw_row_and_review_only_assertions():
    row = {
        "name": "~Aa argyrolepis Rchb.f. 1854",
        "season": "winter, spring",
        "temperature": "cold",
        "description": "<p>Found in Peru.</p>",
        "references": "IPNI; Tropicos",
    }
    record = adapt_iospe_row(row, row_number=3)
    assert record.editorial_marker == "~"
    assert record.source_taxon_name.startswith("Aa argyrolepis")
    assert record.raw_fields["name"].startswith("~")
    assert all(a.review_state == "review_required" for a in record.assertions)
    assert len(record.row_sha256) == 64


def test_exact_hassler_reconciliation():
    record = adapt_iospe_row({"name": "Aa argyrolepis Rchb.f. 1854"}, row_number=3)
    resolved = reconcile_source_record(record, _registry())
    assert resolved.canonical_name == "Aa argyrolepis"
    assert resolved.reconciliation_status == "exact_accepted"


def test_synonym_reconciliation_resolves_to_hassler_accepted_taxon():
    record = adapt_iospe_row({"name": "Ephippium ciliatum"}, row_number=7)
    resolved = reconcile_source_record(record, _registry())
    assert resolved.canonical_name == "Bulbophyllum maxillare"
    assert resolved.reconciliation_status == "synonym_resolved"


def test_yong_gee_adapter_maps_fields_without_declaring_them_canonical():
    row = {
        "id": "stable-1",
        "websiteInformalName": "Aa argyrolepis",
        "distributionsp": "Peru and Bolivia",
        "habitat": "montane grassland",
        "season": "spring",
        "referencesp": "Example monograph",
    }
    record = adapt_yong_gee_row(row, row_number=2)
    assert record.source_record_id == "yong_gee:stable-1"
    assert record.provenance["coverage"] == "representative_extract_not_complete"
    predicates = {a.predicate for a in record.assertions}
    assert "geography.distribution" in predicates
    assert "ecology.habitat" in predicates


def test_comparison_preserves_conflicting_claims():
    jay = adapt_iospe_row({"name": "Aa argyrolepis", "season": "winter"}, row_number=1)
    gary = adapt_yong_gee_row(
        {"id": "x", "websiteInformalName": "Aa argyrolepis", "season": "spring"},
        row_number=1,
    )
    compared = compare_assertions([jay, gary])
    assert compared["phenology.flowering_season"]["relationship"] == (
        "multiple_source_claims_review_required"
    )
    assert len(compared["phenology.flowering_season"]["claims"]) == 2
