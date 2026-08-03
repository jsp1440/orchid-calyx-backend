from __future__ import annotations

from datetime import datetime

from app.parallel_platform.homepage_selection import (
    HomepageFeatureCandidate,
    HomepageImageCandidate,
    select_homepage_feature,
)
from app.parallel_platform.identification_candidates import (
    IdentificationCandidateRecord,
    rank_identification_candidates,
)
from app.parallel_platform.identification_observations import (
    CharacterObservation,
    OrchidObservation,
)
from app.parallel_platform.integration_contracts import (
    HomepageSelectionRequest,
    IdentificationSessionRequest,
    MatrixNeighborhoodRequest,
)
from app.parallel_platform.matrix_adapters import DimensionEvidence
from app.parallel_platform.matrix_neighborhood import (
    MatrixNeighborCandidate,
    rank_matrix_neighbors,
)

CONTRACT_VERSION = "oc-parallel-v1"


def matrix_neighborhood(request: MatrixNeighborhoodRequest) -> dict[str, object]:
    candidates = tuple(
        MatrixNeighborCandidate(
            taxon_id=item.taxon_id,
            accepted_name=item.accepted_name,
            dimensions={
                dimension: DimensionEvidence(
                    dimension=dimension,
                    availability=evidence.availability,
                    score=evidence.score,
                    confidence=evidence.confidence,
                    evidence=tuple(evidence.evidence),
                    provenance=tuple(evidence.provenance),
                    limitations=tuple(evidence.limitations),
                )
                for dimension, evidence in item.dimensions.items()
            },
        )
        for item in request.candidates
    )
    ranked = rank_matrix_neighbors(
        candidates,
        weights=request.weights,
        limit=request.limit,
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "subject_taxon_id": request.subject_taxon_id,
        "neighbors": [item.as_dict() for item in ranked],
        "publication_authority": False,
    }


def identification_session(request: IdentificationSessionRequest) -> dict[str, object]:
    observation = OrchidObservation(
        observation_id=request.observation_id,
        characters=tuple(
            CharacterObservation(
                character=item.character,
                state=item.state,
                value=item.value,
                confidence=item.confidence,
                source_media_ids=tuple(item.source_media_ids),
                notes=item.notes,
            )
            for item in request.observations
        ),
        provenance=tuple(request.provenance),
    )
    candidates = tuple(
        IdentificationCandidateRecord(
            taxon_id=item.taxon_id,
            accepted_name=item.scientific_name,
            features=item.features,
            provenance=tuple(item.evidence),
        )
        for item in request.candidates
    )
    result = rank_identification_candidates(observation, candidates)
    return {
        "contract_version": CONTRACT_VERSION,
        "observation_id": request.observation_id,
        **result,
    }


def homepage_selection(request: HomepageSelectionRequest) -> dict[str, object]:
    if request.feature_type not in {"featured_genus", "featured_species"}:
        raise ValueError("INVALID_HOMEPAGE_FEATURE_TYPE")

    candidates = tuple(
        HomepageFeatureCandidate(
            taxon_id=item.taxon_id,
            accepted_name=item.scientific_name,
            content_score=item.content_score,
            freshness_at=(datetime.fromisoformat(item.freshness_at) if item.freshness_at else None),
            provenance=tuple(item.evidence) or (item.source,),
            images=(
                HomepageImageCandidate(
                    image_id=f"{item.taxon_id}:primary",
                    url=item.image_url,
                    license=item.image_license,
                    attribution=item.image_attribution,
                    approved_source=item.source
                    in {"orchid-continuum", "inat-s3", "flickr", "wikimedia", "supabase"},
                    is_herbarium_or_document_plate=item.image_kind
                    in {"herbarium", "document_plate"},
                ),
            )
            if item.image_url
            else (),
        )
        for item in request.candidates
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "feature_type": request.feature_type,
        **select_homepage_feature(candidates),
        "publication_authority": False,
    }
