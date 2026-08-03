from app.parallel_platform.matrix_adapters import DimensionEvidence
from app.parallel_platform.matrix_neighborhood import (
    MatrixNeighborCandidate,
    rank_matrix_neighbors,
)


def test_missing_dimensions_do_not_reduce_score_to_zero():
    candidate = MatrixNeighborCandidate(
        taxon_id="taxon:1",
        accepted_name="Example orchid",
        dimensions={
            "taxonomy": DimensionEvidence(
                dimension="taxonomy",
                availability="available",
                score=0.9,
                confidence=0.8,
            )
        },
    )
    result = rank_matrix_neighbors((candidate,))[0]
    assert result.score == 0.9
    assert result.evidence_coverage < 0.1
    assert "morphology" in result.unavailable_dimensions


def test_neighbors_are_ranked_deterministically():
    first = MatrixNeighborCandidate(
        taxon_id="taxon:a",
        accepted_name="Alpha",
        dimensions={
            "taxonomy": DimensionEvidence(
                dimension="taxonomy", availability="available", score=0.8
            )
        },
    )
    second = MatrixNeighborCandidate(
        taxon_id="taxon:b",
        accepted_name="Beta",
        dimensions={
            "taxonomy": DimensionEvidence(
                dimension="taxonomy", availability="available", score=0.9
            )
        },
    )
    ranked = rank_matrix_neighbors((first, second), limit=1)
    assert ranked[0].taxon_id == "taxon:b"
    assert ranked[0].as_dict()["verified_relationship"] is False
