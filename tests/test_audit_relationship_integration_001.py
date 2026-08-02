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
