from __future__ import annotations

import json

import pytest

from app.calyx_orchestrator.atlas_product_path import (
    AtlasEvidenceState,
    AtlasNavigationGateway,
    AtlasProductPath,
    AtlasTourContentState,
    CanonicalTaxonBinding,
    build_unavailable_atlas_snapshot,
    choose_taxon_binding,
)


def _binding(source_class: str, *, reviewed: bool, taxon_id: str = "taxon:1") -> CanonicalTaxonBinding:
    return CanonicalTaxonBinding(
        taxon_id=taxon_id,
        scientific_name="Laelia anceps",
        source_class=source_class,
        reviewed=reviewed,
    )


def test_unavailable_gateway_returns_explicit_unavailable_snapshot() -> None:
    path = AtlasNavigationGateway(available=False).get_product_path(
        entry_point="species", taxon_id="taxon:1"
    )
    payload = path.to_dict()
    assert payload["evidence_state"] == "UNAVAILABLE"
    assert payload["taxon_binding"] is None
    assert payload["occurrence_context_available"] is None
    assert payload["tour_content_state"] == "UNAVAILABLE"
    assert payload["occurrence_context"] is None
    assert payload["tour_content"] is None


def test_build_unavailable_atlas_snapshot_is_all_unavailable() -> None:
    path = build_unavailable_atlas_snapshot("genus")
    assert path.entry_point == "genus"
    assert path.evidence_state is AtlasEvidenceState.UNAVAILABLE
    assert path.taxon_binding is None
    assert path.occurrence_context_available is None
    assert path.tour_content_state is AtlasTourContentState.UNAVAILABLE


def test_reviewed_binding_outranks_unreviewed_and_provisional() -> None:
    selected = choose_taxon_binding(
        [
            _binding("provisional", reviewed=False),
            _binding("canonical_unreviewed", reviewed=False),
            _binding("canonical_reviewed", reviewed=True),
        ]
    )
    assert selected is not None
    assert selected.source_class == "canonical_reviewed"
    assert selected.reviewed is True


def test_gateway_never_fabricates_occurrence_presence() -> None:
    path = AtlasNavigationGateway(
        available=True,
        bindings=[_binding("canonical_reviewed", reviewed=True)],
    ).get_product_path(entry_point="species", taxon_id="taxon:1")
    assert path.occurrence_context_available is None
    assert path.occurrence_context is None


def test_pending_or_draft_tour_content_cannot_be_exposed_as_available() -> None:
    gateway = AtlasNavigationGateway(
        available=True,
        bindings=[_binding("canonical_reviewed", reviewed=True)],
        pending_tour_taxa={"taxon:1"},
    )
    path = gateway.get_product_path(entry_point="species", taxon_id="taxon:1")
    assert path.tour_content_state is AtlasTourContentState.PENDING_REVIEW
    assert path.tour_content is None

    with pytest.raises(ValueError, match="draft or unavailable tour content cannot be exposed"):
        AtlasProductPath(
            entry_point="species",
            taxon_binding=_binding("canonical_reviewed", reviewed=True),
            occurrence_context_available=None,
            tour_content_state=AtlasTourContentState.DRAFT,
            evidence_state=AtlasEvidenceState.REVIEW_REQUIRED,
            tour_content={"title": "unpublished"},
        )


def test_available_tour_content_must_be_explicitly_reviewed_content() -> None:
    with pytest.raises(ValueError, match="AVAILABLE tour content requires reviewed content"):
        AtlasProductPath(
            entry_point="species",
            taxon_binding=_binding("canonical_reviewed", reviewed=True),
            occurrence_context_available=None,
            tour_content_state=AtlasTourContentState.AVAILABLE,
            evidence_state=AtlasEvidenceState.VERIFIED,
        )


def test_serialization_redacts_private_locality_and_preserves_governance_flags() -> None:
    gateway = AtlasNavigationGateway(
        available=True,
        bindings=[_binding("canonical_reviewed", reviewed=True)],
        occurrence_context_by_taxon={
            "taxon:1": {
                "record_count": 3,
                "source": "reviewed-occurrence-summary",
                "latitude": 34.1,
                "longitude": -120.7,
                "private_locality": "restricted canyon",
                "nested": {"coordinates": [34.1, -120.7], "safe": "regional summary"},
            }
        },
        reviewed_tour_content_by_taxon={
            "taxon:1": {"title": "Reviewed Atlas tour", "summary": "regional context only"}
        },
    )
    payload = gateway.get_product_path(entry_point="species", taxon_id="taxon:1").to_dict()
    encoded = json.dumps(payload).casefold()

    assert payload["occurrence_context_available"] is True
    assert payload["tour_content_state"] == "AVAILABLE"
    assert payload["automatic_publication"] is False
    assert payload["taxonomy_activation"] is False
    assert payload["production_mutation"] is False
    assert '"latitude"' not in encoded
    assert '"longitude"' not in encoded
    assert '"coordinates"' not in encoded
    assert '"private_locality"' not in encoded
    assert "regional summary" in encoded


def test_human_review_gate_cannot_be_disabled() -> None:
    with pytest.raises(ValueError, match="human-review gated"):
        AtlasProductPath(
            entry_point="species",
            taxon_binding=None,
            occurrence_context_available=None,
            tour_content_state=AtlasTourContentState.UNAVAILABLE,
            evidence_state=AtlasEvidenceState.UNKNOWN,
            human_review_required=False,
        )
