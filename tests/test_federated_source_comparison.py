from runtime.federated_sources.comparison import compare_evidence_rows


def test_exact_agreement_is_literal_and_source_preserving():
    rows = [
        {
            "taxon_pk": "42",
            "evidence_type": "phenology",
            "excerpt": "Spring",
            "source_name": "Gary Yong Gee Orchid Database",
            "source_record_id": "g1",
            "claim_label": "season",
            "citation": "Gary",
            "review_state": "source_imported_taxonomy_matched",
        },
        {
            "taxon_pk": "42",
            "evidence_type": "phenology",
            "excerpt": " spring ",
            "source_name": "Internet Orchid Species Photo Encyclopedia",
            "source_record_id": "j1",
            "claim_label": "season",
            "citation": "IOSPE",
            "review_state": "source_imported_taxonomy_matched",
        },
    ]
    result = compare_evidence_rows(rows)
    assert result[0]["relationship"] == "exact_agreement"
    assert result[0]["source_count"] == 2
    assert len(result[0]["claims"]) == 2


def test_different_values_are_never_averaged():
    rows = [
        {"taxon_pk": "42", "evidence_type": "phenology", "excerpt": "winter",
         "source_name": "Gary", "source_record_id": "g1"},
        {"taxon_pk": "42", "evidence_type": "phenology", "excerpt": "spring",
         "source_name": "IOSPE", "source_record_id": "j1"},
    ]
    result = compare_evidence_rows(rows)
    assert result[0]["relationship"] == "multiple_source_claims_review_required"
    assert {c["excerpt"] for c in result[0]["claims"]} == {"winter", "spring"}
