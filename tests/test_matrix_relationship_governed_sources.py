import pytest

from runtime.matrix_relationship import build_relationship_matrix
from runtime.matrix_relationship_sources import (
    governed_source_dimensions,
    rows_to_assertions,
)


def test_governed_dimensions_are_only_enabled_relationship_sources():
    assert governed_source_dimensions() == [
        "conservation_status",
        "elevation",
        "geography",
        "literature",
        "mycorrhizal_partner",
        "pollinator",
        "trait",
    ]


def test_pollinator_rows_become_present_assertions_with_provenance():
    assertions = rows_to_assertions(
        "pollinator",
        [
            {
                "source_pk": 23,
                "taxon_pk": 101,
                "subject_label": "Phalaenopsis amabilis",
                "partner_taxon_name": "Xylocopa confusa",
                "evidence_class": "literature",
                "evidence_citation": "Example citation",
                "confidence_score": 0.82,
            }
        ],
    )
    assertion = assertions[0]
    assert assertion.state == "present"
    assert assertion.subject_id == "101"
    assert assertion.object_label == "Xylocopa confusa"
    assert assertion.confidence == 0.82
    assert assertion.provenance == {
        "source_domain": "pollinators",
        "source_query_id": "pollinators_interaction_edges_v1",
        "source_pk": "23",
        "evidence_class": "literature",
        "evidence_citation": "Example citation",
    }


def test_mycorrhiza_uses_fungal_taxon_id_when_available():
    assertion = rows_to_assertions(
        "mycorrhizal_partner",
        [
            {
                "source_pk": "assoc-1",
                "taxon_pk": 202,
                "subject_label": "Orchis mascula",
                "fungal_name": "Tulasnella calospora",
                "fungal_taxon_id": 998,
                "citation": "Example mycorrhiza source",
                "confidence_score": 0.7,
            }
        ],
    )[0]
    assert assertion.object_id == "fungus-taxon:998"
    assert assertion.object_label == "Tulasnella calospora"
    assert assertion.provenance["source_domain"] == "mycorrhiza"


def test_literature_prefers_doi_identity_and_preserves_year():
    assertion = rows_to_assertions(
        "literature",
        [
            {
                "source_pk": 77,
                "taxon_pk": 303,
                "subject_label": "Laelia anceps",
                "title": "A paper about Laelia",
                "doi": "10.1000/example",
                "year": 2024,
                "confidence_score": 0.91,
            }
        ],
    )[0]
    assert assertion.object_id == "doi:10.1000/example"
    assert assertion.provenance["year"] == 2024


def test_trait_rows_use_name_value_identity_and_preserve_support():
    assertion = rows_to_assertions(
        "trait",
        [
            {
                "source_pk": "trait-row-1",
                "taxon_pk": 404,
                "subject_label": "Phalaenopsis schilleriana",
                "trait_name": "growth_habit",
                "trait_value": "epiphytic",
                "support_count": 4,
                "confidence_score": 0.88,
                "confidence_label": "high",
            }
        ],
    )[0]
    assert assertion.object_id == "trait:growth_habit=epiphytic"
    assert assertion.object_label == "growth_habit: epiphytic"
    assert assertion.confidence == 0.88
    assert assertion.provenance["source_domain"] == "traits"
    assert assertion.provenance["source_query_id"] == "traits_resolved_v4"
    assert assertion.provenance["support_count"] == 4
    assert assertion.provenance["confidence_label"] == "high"


def test_conservation_rows_use_status_identity_and_preserve_provenance():
    assertion = rows_to_assertions(
        "conservation_status",
        [
            {
                "source_pk": "conservation-1",
                "taxon_pk": 505,
                "subject_label": "Paphiopedilum rothschildianum",
                "iucn_category": "EN",
                "cites_appendix": "I",
                "population_trend": "decreasing",
                "assessment_year": 2025,
                "region": "global",
                "source_name": "IUCN/CITES",
                "evidence_class": "IUCN/CITES",
            }
        ],
    )[0]
    assert assertion.object_id == "conservation:iucn=en|cites=i"
    assert assertion.object_label == "IUCN: EN; CITES: I"
    assert assertion.state == "present"
    assert assertion.provenance["source_domain"] == "conservation"
    assert assertion.provenance["source_query_id"] == "conservation_v1"
    assert assertion.provenance["population_trend"] == "decreasing"
    assert assertion.provenance["assessment_year"] == 2025
    assert assertion.provenance["source_name"] == "IUCN/CITES"


def test_geography_uses_country_only_and_does_not_expose_locality_coordinates():
    assertion = rows_to_assertions(
        "geography",
        [
            {
                "source_pk": "occ-1",
                "taxon_pk": 606,
                "subject_label": "Laelia anceps",
                "country": "Mexico",
                "locality": "Sensitive ravine",
                "latitude": 19.1234,
                "longitude": -99.5678,
                "event_date": "2024-03-01",
                "basis_of_record": "HUMAN_OBSERVATION",
                "source_name": "GBIF",
            }
        ],
    )[0]
    assert assertion.object_id == "country:mexico"
    assert assertion.object_label == "Mexico"
    assert assertion.state == "present"
    assert assertion.provenance["source_domain"] == "occurrences"
    assert assertion.provenance["source_query_id"] == "occurrences_v1"
    assert assertion.provenance["country"] == "Mexico"
    assert assertion.provenance["source_name"] == "GBIF"
    assert "locality" not in assertion.provenance
    assert "latitude" not in assertion.provenance
    assert "longitude" not in assertion.provenance


def test_elevation_uses_recorded_occurrence_value_without_inferred_range():
    assertion = rows_to_assertions(
        "elevation",
        [
            {
                "source_pk": "occ-2",
                "taxon_pk": 707,
                "subject_label": "Dracula lotax",
                "elevation": "1850.0",
                "country": "Ecuador",
                "source_name": "iNaturalist",
            }
        ],
    )[0]
    assert assertion.object_id == "elevation_m:1850"
    assert assertion.object_label == "Elevation: 1850 m"
    assert assertion.state == "present"
    assert assertion.provenance["source_domain"] == "occurrences"
    assert assertion.provenance["source_query_id"] == "occurrences_v1"
    assert assertion.provenance["elevation"] == "1850.0"
    assert assertion.provenance["country"] == "Ecuador"


def test_source_rows_never_invent_absence_for_missing_pairs():
    assertions = rows_to_assertions(
        "pollinator",
        [
            {
                "source_pk": 1,
                "taxon_pk": 101,
                "subject_label": "Taxon A",
                "partner_taxon_name": "Bee A",
            }
        ],
    )
    matrix = build_relationship_matrix(
        assertions,
        dimension="pollinator",
        subject_ids=["101", "999"],
        object_ids=["pollinator:bee a"],
    )
    states = {cell["subject_id"]: cell["state"] for cell in matrix["cells"]}
    assert states == {"101": "present", "999": "not_recorded"}


def test_trait_source_rows_never_invent_absence_for_missing_taxa():
    assertions = rows_to_assertions(
        "trait",
        [
            {
                "source_pk": "trait-row-2",
                "taxon_pk": 404,
                "subject_label": "Taxon A",
                "trait_name": "growth_habit",
                "trait_value": "epiphytic",
            }
        ],
    )
    matrix = build_relationship_matrix(
        assertions,
        dimension="trait",
        subject_ids=["404", "999"],
        object_ids=["trait:growth_habit=epiphytic"],
    )
    states = {cell["subject_id"]: cell["state"] for cell in matrix["cells"]}
    assert states == {"404": "present", "999": "not_recorded"}


def test_conservation_source_rows_never_invent_absence_for_missing_taxa():
    assertions = rows_to_assertions(
        "conservation_status",
        [
            {
                "source_pk": "conservation-2",
                "taxon_pk": 505,
                "subject_label": "Taxon A",
                "iucn_category": "VU",
            }
        ],
    )
    matrix = build_relationship_matrix(
        assertions,
        dimension="conservation_status",
        subject_ids=["505", "999"],
        object_ids=["conservation:iucn=vu"],
    )
    states = {cell["subject_id"]: cell["state"] for cell in matrix["cells"]}
    assert states == {"505": "present", "999": "not_recorded"}


def test_unsupported_or_incomplete_rows_fail_closed():
    with pytest.raises(ValueError, match="unsupported governed matrix dimension"):
        rows_to_assertions("climate", [])

    with pytest.raises(ValueError, match="missing fungal_name"):
        rows_to_assertions(
            "mycorrhizal_partner",
            [
                {
                    "source_pk": "assoc-2",
                    "taxon_pk": 202,
                    "subject_label": "Orchis mascula",
                }
            ],
        )

    with pytest.raises(ValueError, match="missing trait_value"):
        rows_to_assertions(
            "trait",
            [
                {
                    "source_pk": "trait-row-3",
                    "taxon_pk": 404,
                    "subject_label": "Phalaenopsis schilleriana",
                    "trait_name": "growth_habit",
                }
            ],
        )

    with pytest.raises(ValueError, match="missing iucn_category/cites_appendix"):
        rows_to_assertions(
            "conservation_status",
            [
                {
                    "source_pk": "conservation-3",
                    "taxon_pk": 505,
                    "subject_label": "Paphiopedilum rothschildianum",
                }
            ],
        )

    with pytest.raises(ValueError, match="missing country"):
        rows_to_assertions(
            "geography",
            [
                {
                    "source_pk": "occ-3",
                    "taxon_pk": 606,
                    "subject_label": "Laelia anceps",
                }
            ],
        )

    with pytest.raises(ValueError, match="missing elevation"):
        rows_to_assertions(
            "elevation",
            [
                {
                    "source_pk": "occ-4",
                    "taxon_pk": 707,
                    "subject_label": "Dracula lotax",
                }
            ],
        )

    with pytest.raises(ValueError, match="invalid elevation"):
        rows_to_assertions(
            "elevation",
            [
                {
                    "source_pk": "occ-5",
                    "taxon_pk": 707,
                    "subject_label": "Dracula lotax",
                    "elevation": "NaN",
                }
            ],
        )