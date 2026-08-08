from runtime.terrestrial_orchid_propagation_comparators import (
    comparator_matrix,
    comparator_observations,
    comparator_sources,
    vegetative_plb_bridge_assessment,
)


def test_comparator_sources_are_independent_terrestrial_orchid_evidence():
    sources = comparator_sources()
    assert {source.taxon for source in sources} == {
        "Spathoglottis plicata",
        "Ipsea malabarica",
        "Hemipilia cucullata",
        "Anoectochilus roxburghii",
    }
    assert all(source.terrestrial_orchid for source in sources)
    assert all(
        source.evidence_completeness
        in {"pubmed_abstract_verified", "publisher_open_access_abstract_verified"}
        for source in sources
    )


def test_spathoglottis_nodal_explant_has_direct_vegetative_plb_response():
    observation = next(
        item for item in comparator_observations() if item.observation_id == "sp-nodal-plb-001"
    )
    assert observation.explant == "nodal explant"
    assert observation.quantitative_value == 98.5
    assert observation.directly_about_thelymitra is False


def test_ipsea_preserves_positive_and_negative_treatment_evidence():
    observations = comparator_observations()
    positive = next(item for item in observations if item.observation_id == "im-axillary-plb-001")
    negative = next(item for item in observations if item.observation_id == "im-kin-negative-002")
    assert positive.explant == "axillary bud"
    assert positive.response_time_days == 25.0
    assert positive.quantitative_value == 33.1
    assert negative.direction == "negative_for_plb_induction"
    assert "did not induce PLBs" in negative.response


def test_hemipilia_leaf_explant_adds_endangered_terrestrial_comparator():
    observation = next(
        item for item in comparator_observations() if item.observation_id == "hc-leaf-plb-001"
    )
    assert observation.explant == "sterile leaf explant"
    assert observation.quantitative_value == 44.3
    assert dict(observation.treatment)["BA"] == "3 mg/L"
    assert dict(observation.treatment)["NAA"] == "0.2 mg/L"


def test_anoectochilus_has_direct_meristem_to_plb_comparator():
    observation = next(
        item for item in comparator_observations() if item.observation_id == "ar-meristem-plb-001"
    )
    assert observation.explant == "axillary bud meristem"
    assert "without intervening callus" in observation.response
    assert observation.quantitative_value == 30.0
    assert observation.directly_about_thelymitra is False


def test_comparator_matrix_preserves_source_provenance_and_no_thelymitra_claim():
    rows = comparator_matrix()
    assert len(rows) == 9
    assert all(row["source"]["doi"] or row["source"]["pmid"] for row in rows)
    assert all(row["directly_about_thelymitra"] is False for row in rows)
    assert all(row["publication_authority"] is False for row in rows)


def test_bridge_assessment_is_precedent_not_prediction():
    assessment = vegetative_plb_bridge_assessment()
    assert assessment["answer_state"] == "documented_in_other_terrestrial_orchids"
    assert assessment["supporting_taxa"] == [
        "Anoectochilus roxburghii",
        "Hemipilia cucullata",
        "Ipsea malabarica",
        "Spathoglottis plicata",
    ]
    assert assessment["direct_meristem_to_plb_comparator_ids"] == ["ar-meristem-plb-001"]
    assert assessment["rhizome_linked_vegetative_comparator_ids"] == ["im-axillary-plb-001"]
    assert assessment["direct_thelymitra_evidence"] is False
    assert assessment["prediction_of_thelymitra_success"] is False
    assert assessment["scientific_review_required"] is True
    assert assessment["publication_authority"] is False
