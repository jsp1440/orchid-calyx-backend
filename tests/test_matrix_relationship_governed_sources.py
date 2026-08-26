import pytest

from runtime.matrix_relationship import build_relationship_matrix
from runtime.matrix_relationship_sources import (
    governed_source_dimensions,
    rows_to_assertions,
)


def test_governed_dimensions_are_only_enabled_relationship_sources():
    assert governed_source_dimensions() == [
        "literature",
        "mycorrhizal_partner",
        "pollinator",
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


def test_unsupported_or_incomplete_rows_fail_closed():
    with pytest.raises(ValueError, match="unsupported governed matrix dimension"):
        rows_to_assertions("elevation", [])

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
