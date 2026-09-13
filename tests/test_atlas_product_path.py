import json

import pytest

from app.calyx_orchestrator.atlas_product_path import (
    AtlasEntryPoint,
    AtlasEvidenceState,
    AtlasNavigationGateway,
    AtlasOccurrenceState,
    AtlasProductPath,
    AtlasTaxonReviewState,
    AtlasTourContentState,
    CanonicalTaxonBinding,
    build_unavailable_atlas_snapshot,
    select_canonical_taxon_binding,
)


def _binding(
    taxon_id: str = "taxon-1",
    *,
    rank: AtlasEntryPoint = AtlasEntryPoint.SPECIES,
    review_state: AtlasTaxonReviewState = AtlasTaxonReviewState.REVIEWED,
    source: str = "canonical-registry",
) -> CanonicalTaxonBinding:
    return CanonicalTaxonBinding(
        canonical_taxon_id=taxon_id,
        scientific_name="Cattleya labiata",
        rank=rank,
        source=source,
        review_state=review_state,
    )


def _available_species_path() -> AtlasProductPath:
    return AtlasProductPath(
        entry_point=AtlasEntryPoint.SPECIES,
        taxon_binding=_binding(),
        occurrence_state=AtlasOccurrenceState.AVAILABLE,
        occurrence_count=3,
        tour_content_state=AtlasTourContentState.AVAILABLE,
        tour_content="Reviewed public tour.",
        evidence_state=AtlasEvidenceState.PRESENT,
        human_review_required=False,
    )


def test_unavailable_snapshot_is_explicit_and_does_not_infer_absence() -> None:
    snapshot = build_unavailable_atlas_snapshot(AtlasEntryPoint.SPECIES)

    assert snapshot.species_present is None
    assert snapshot.to_dict()["occurrence_context"] == {
        "state": "unavailable",
        "count": None,
        "species_present": None,
    }
    assert snapshot.to_dict()["evidence_state"] == "unavailable"


@pytest.mark.parametrize("loader", [None, lambda _entry_point: None])
def test_gateway_fails_closed_when_atlas_persistence_is_unavailable(loader) -> None:
    snapshot = AtlasNavigationGateway(loader).resolve(AtlasEntryPoint.GENUS)

    assert snapshot.entry_point is AtlasEntryPoint.GENUS
    assert snapshot.taxon_binding is None
    assert snapshot.evidence_state is AtlasEvidenceState.UNAVAILABLE


def test_canonical_selection_prefers_reviewed_identity_independent_of_order() -> None:
    provisional = _binding(
        "taxon-a",
        review_state=AtlasTaxonReviewState.PROVISIONAL,
    )
    reviewed = _binding(
        "taxon-z",
        review_state=AtlasTaxonReviewState.REVIEWED,
    )

    assert select_canonical_taxon_binding([provisional, reviewed]) is reviewed
    assert select_canonical_taxon_binding([reviewed, provisional]) is reviewed


def test_canonical_selection_has_a_stable_tie_breaker() -> None:
    later = _binding("taxon-z", source="registry-b")
    earlier = _binding("taxon-a", source="registry-z")

    assert select_canonical_taxon_binding([later, earlier]) is earlier
    assert select_canonical_taxon_binding([earlier, later]) is earlier


def test_available_species_path_is_json_serializable_and_evidence_backed() -> None:
    public = _available_species_path().to_dict()

    assert public["taxon_binding"]["canonical_taxon_id"] == "taxon-1"
    assert public["occurrence_context"] == {
        "state": "available",
        "count": 3,
        "species_present": True,
    }
    assert json.loads(json.dumps(public, sort_keys=True)) == public


@pytest.mark.parametrize(
    "state",
    [AtlasTourContentState.DRAFT, AtlasTourContentState.PENDING_REVIEW],
)
def test_non_public_tour_content_cannot_cross_the_navigation_boundary(state) -> None:
    with pytest.raises(ValueError, match="must be withheld"):
        AtlasProductPath(
            entry_point=AtlasEntryPoint.SPECIES,
            taxon_binding=_binding(),
            occurrence_state=AtlasOccurrenceState.ABSENT,
            occurrence_count=None,
            tour_content_state=state,
            tour_content="unpublished draft",
            evidence_state=AtlasEvidenceState.UNKNOWN,
            human_review_required=True,
        )


def test_available_tour_requires_completed_human_review() -> None:
    with pytest.raises(ValueError, match="unreviewed tour content"):
        AtlasProductPath(
            entry_point=AtlasEntryPoint.SPECIES,
            taxon_binding=_binding(),
            occurrence_state=AtlasOccurrenceState.ABSENT,
            occurrence_count=None,
            tour_content_state=AtlasTourContentState.AVAILABLE,
            tour_content="not yet reviewed",
            evidence_state=AtlasEvidenceState.UNKNOWN,
            human_review_required=True,
        )


def test_public_contract_has_no_locality_or_activation_authority() -> None:
    public = _available_species_path().to_dict()
    serialized = json.dumps(public, sort_keys=True).casefold()

    for forbidden in ("latitude", "longitude", "coordinates", "private_locality"):
        assert forbidden not in serialized
    assert public["publication_authorized"] is False
    assert public["taxonomy_activation_authorized"] is False


def test_binding_rank_must_match_entry_point() -> None:
    with pytest.raises(ValueError, match="rank must match"):
        AtlasProductPath(
            entry_point=AtlasEntryPoint.GENUS,
            taxon_binding=_binding(rank=AtlasEntryPoint.SPECIES),
            occurrence_state=AtlasOccurrenceState.UNAVAILABLE,
            occurrence_count=None,
            tour_content_state=AtlasTourContentState.UNAVAILABLE,
            tour_content=None,
            evidence_state=AtlasEvidenceState.UNKNOWN,
            human_review_required=True,
        )


def test_gateway_rejects_mismatched_loader_result() -> None:
    gateway = AtlasNavigationGateway(lambda _entry_point: _available_species_path())

    with pytest.raises(ValueError, match="mismatched entry point"):
        gateway.resolve(AtlasEntryPoint.GENUS)
