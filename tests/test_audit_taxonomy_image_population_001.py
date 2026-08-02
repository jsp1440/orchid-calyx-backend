from runtime.relationship_integration import RelationshipIntegrationAudit
from runtime.taxonomy_image_population import (
    MediaAsset,
    RecordMediaLink,
    build_taxonomy_image_candidates,
)


def test_exact_taxon_media_links_create_verified_provenance_links():
    result = build_taxonomy_image_candidates(
        links=[RecordMediaLink("taxonomy", "taxon:123", "media:9")],
        assets={
            "media:9": MediaAsset(
                "media:9", "iNaturalist", "obs-42", "CC-BY"
            )
        },
        canonical_taxon_ids={"taxon:123"},
    )

    assert result.summary() == {
        "candidate_links": 1,
        "linked_taxa": 1,
        "rejected": 0,
        "rejection_reasons": [],
    }
    candidate = result.candidates[0]
    assert candidate.match_method == "canonical_record_media_link"
    assert candidate.validation_status == "verified"
    assert candidate.provenance["media_provider"] == "iNaturalist"
    report = RelationshipIntegrationAudit(result.candidates).report()
    assert report["coverage"]["taxonomy_to_images"]["present"] is True
    assert report["knowledge_graph_node_edge_integrity"]["passed"] is True


def test_unknown_taxa_missing_assets_and_duplicates_are_rejected():
    links = [
        RecordMediaLink("taxonomy", "taxon:404", "media:1"),
        RecordMediaLink("taxonomy", "taxon:1", "media:missing"),
        RecordMediaLink("taxonomy", "taxon:1", "media:1"),
        RecordMediaLink("taxonomy", "taxon:1", "media:1"),
        RecordMediaLink("occurrence", "taxon:1", "media:2"),
    ]
    assets = {
        "media:1": MediaAsset("media:1", "Wikimedia"),
        "media:2": MediaAsset("media:2", "GBIF"),
    }

    result = build_taxonomy_image_candidates(links, assets, {"taxon:1"})

    assert len(result.candidates) == 1
    assert {item["reason"] for item in result.rejected} == {
        "unknown_taxon_id",
        "missing_media_asset",
        "duplicate_record_media_link",
        "unsupported_record_domain",
    }


def test_name_only_records_are_not_accepted_as_taxon_identifiers():
    result = build_taxonomy_image_candidates(
        [RecordMediaLink("taxonomy", "Cattleya labiata", "media:1")],
        {"media:1": MediaAsset("media:1", "provider")},
        {"taxon:123"},
    )

    assert not result.candidates
    assert result.rejected[0]["reason"] == "unknown_taxon_id"
