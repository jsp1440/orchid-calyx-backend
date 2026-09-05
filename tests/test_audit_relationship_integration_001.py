import pytest

from runtime.relationship_integration import (
    RelationshipIntegrationAudit,
    RelationshipLink,
)


def link(target_domain: str, target_id: str = "target-1") -> RelationshipLink:
    return RelationshipLink(
        source_domain="taxonomy",
        source_record_id="taxon-1",
        target_domain=target_domain,
        target_record_id=target_id,
        relationship_type=f"taxonomy_to_{target_domain}",
        taxon_id="taxon-1",
        match_method="canonical_taxon_id",
        provenance={"source": "test"},
        validation_status="verified",
    )


def test_reports_present_and_missing_relationships():
    report = RelationshipIntegrationAudit(
        [link("images"), link("occurrences"), link("literature")]
    ).report()

    assert report["coverage"]["taxonomy_to_images"]["present"] is True
    assert report["coverage"]["taxonomy_to_images"]["linked_taxa"] == 1
    assert report["coverage"]["taxonomy_to_occurrences"]["verified_links"] == 1
    assert "taxonomy_to_pollinators" in report["missing_relationships"]


def test_detects_duplicate_edges_and_self_loops():
    duplicate = link("images")
    self_loop = RelationshipLink(
        source_domain="taxonomy",
        source_record_id="taxon-1",
        target_domain="taxonomy",
        target_record_id="taxon-1",
        relationship_type="same_as",
        taxon_id="taxon-1",
        match_method="canonical_taxon_id",
        provenance={"source": "test"},
    )
    report = RelationshipIntegrationAudit([duplicate, duplicate, self_loop]).report()
    issues = {
        item["issue"]
        for item in report["knowledge_graph_node_edge_integrity"]["issues"]
    }

    assert report["knowledge_graph_node_edge_integrity"]["passed"] is False
    assert {"duplicate_edge", "self_loop"}.issubset(issues)


def test_taxonomy_links_require_taxon_id():
    invalid = RelationshipLink(
        source_domain="taxonomy",
        source_record_id="taxon-1",
        target_domain="images",
        target_record_id="image-1",
        relationship_type="taxonomy_to_images",
        taxon_id=None,
        match_method="name_match",
        provenance={"source": "test"},
    )

    with pytest.raises(ValueError, match="require taxon_id"):
        invalid.validated()


def test_missing_provenance_is_an_integrity_issue():
    no_provenance = RelationshipLink(
        source_domain="taxonomy",
        source_record_id="taxon-1",
        target_domain="images",
        target_record_id="image-1",
        relationship_type="taxonomy_to_images",
        taxon_id="taxon-1",
        match_method="canonical_taxon_id",
    )
    report = RelationshipIntegrationAudit([no_provenance]).report()

    assert report["knowledge_graph_node_edge_integrity"]["issues"][0]["issue"] == (
        "missing_provenance"
    )


def _mycorrhiza_link(status: str, record_id: str) -> RelationshipLink:
    return RelationshipLink(
        source_domain="taxonomy",
        source_record_id="tax-1",
        target_domain="mycorrhiza",
        target_record_id=record_id,
        relationship_type="associated_with",
        taxon_id="tax-1",
        match_method="exact",
        provenance={"source": "study-1"},
        validation_status=status,
    )


def test_withdrawn_links_are_not_counted_as_coverage():
    """A rejected or superseded link is not knowledge the Continuum holds.

    Counting it reported coverage that had been thrown out — the exact failure
    this audit exists to detect, happening inside the audit itself.
    """
    report = RelationshipIntegrationAudit(
        [_mycorrhiza_link("rejected", "m1"), _mycorrhiza_link("superseded", "m2")]
    ).report()
    coverage = report["coverage"]["taxonomy_to_mycorrhiza"]

    assert coverage["present"] is False
    assert coverage["link_count"] == 0
    assert coverage["linked_taxa"] == 0
    assert "taxonomy_to_mycorrhiza" in report["missing_relationships"]


def test_withdrawn_is_distinguished_from_never_asserted():
    """Both have no coverage, and they call for opposite next actions.

    A domain nobody has worked on needs curation started. A domain whose every
    assertion was thrown out needs the rejections read. Reporting them as one
    state sends the reader to the wrong work.
    """
    report = RelationshipIntegrationAudit([_mycorrhiza_link("rejected", "m1")]).report()

    assert report["coverage"]["taxonomy_to_mycorrhiza"]["coverage_state"] == "withdrawn"
    assert report["coverage"]["taxonomy_to_mycorrhiza"]["withdrawn_link_count"] == 1
    # Pollinators were never asserted at all in this audit.
    assert (
        report["coverage"]["taxonomy_to_pollinators"]["coverage_state"]
        == "never_asserted"
    )
    assert report["coverage"]["taxonomy_to_pollinators"]["withdrawn_link_count"] == 0


def test_a_standing_link_still_counts_when_a_sibling_was_withdrawn():
    """Withdrawing one assertion does not withdraw the domain."""
    coverage = RelationshipIntegrationAudit(
        [_mycorrhiza_link("verified", "m1"), _mycorrhiza_link("rejected", "m2")]
    ).report()["coverage"]["taxonomy_to_mycorrhiza"]

    assert coverage["present"] is True
    assert coverage["link_count"] == 1
    assert coverage["verified_links"] == 1
    assert coverage["withdrawn_link_count"] == 1
    assert coverage["coverage_state"] == "present"


def test_provisional_links_still_count_as_coverage():
    """Unreviewed is not withdrawn. A provisional assertion still asserts."""
    coverage = RelationshipIntegrationAudit(
        [_mycorrhiza_link("provisional", "m1")]
    ).report()["coverage"]["taxonomy_to_mycorrhiza"]

    assert coverage["present"] is True
    assert coverage["link_count"] == 1
    # But it is not verified, and the report must not imply that it is.
    assert coverage["verified_links"] == 0
